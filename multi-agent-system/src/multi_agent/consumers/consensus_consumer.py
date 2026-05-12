"""
ConsensusConsumer — consumer Redis Streams para Sprint 4 B.4.5a.

Flujo:
  1. Lee CritiqueMessage del stream agent.critiques.
  2. Lookup ProposalMessage en DB via repo.get_proposal_by_correlation_id.
  3. Sprint 4: invoke consensus.evaluate(proposal, [critique], correlation_id)
     con N=1 critique (solo APOLLO real en Sprint 4). Cuando Sprint 5+ agregue
     HERMES/NYX/VESTA, este consumer necesita aggregator (esperar N critiques
     o timeout antes de evaluar). Por ahora: trigger inmediato.
  4. Persiste DecisionMessage en DB.
  5. Update trades.proposals.status → 'decided'.
  6. Publica DecisionMessage al stream agent.decisions.

Error handling: handler exceptions bubble to AgentMessageBus, which retries
up to max_retries=2 (decisión K3 de B.4.5) and then sends to DLQ.

ConsensusConsumer NO usa LLM — consensus.evaluate es función pure determinística
(ADR-003 D5.2). Constructor solo requiere bus + repo.

Si la proposal NO se encuentra en DB (correlation_id de un critique stale,
proposal eliminada): log warning y return. Eso ACKea el message y previene
loops infinitos en DLQ.

Duplicate protection: trades.decisions tiene UNIQUE(correlation_id) constraint.
Si el handler re-procesa el mismo critique (e.g., bus re-delivery por crash
post-handler-pre-ACK), save_decision raises IntegrityError → bus retry → DLQ.
La decision queda persistida correctamente desde el primer intento exitoso;
el operator ve el DLQ como señal de re-delivery pero no hay data corruption.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..agents import consensus
from ..communication.message_bus import AgentChannels, AgentMessageBus, ConsumerGroups
from ..communication.schemas import CritiqueMessage, ProposalMessage

if TYPE_CHECKING:
    from ..persistence.message_repository import MessageRepository

logger = logging.getLogger(__name__)

CONSUMER_NAME = "consensus-1"
MAX_RETRIES = 2


class ConsensusConsumer:
    """
    Wires AgentMessageBus.CRITIQUES → consensus.evaluate → save_decision →
    update status → publish to DECISIONS.

    Subscribes to the agent.critiques stream with consumer_group=
    CONSENSUS_ENGINE and max_retries=2 (K3). On a handler exception, the
    bus retries twice, then routes the message to the dead-letter stream.

    Sprint 4 N=1 trigger: as soon as a single critique arrives, evaluate
    immediately. With only APOLLO as a real critic, every proposal gets
    exactly one critique. Sprint 5+ adds HERMES/NYX/VESTA — at that point,
    this consumer must aggregate critiques per correlation_id (wait for N
    critics or timeout) before invoking evaluate. The N=1 implementation
    here is the simplest correct behavior for the Sprint 4 cardinality.
    """

    def __init__(
        self,
        bus: AgentMessageBus,
        repo: "MessageRepository",
    ) -> None:
        self._bus = bus
        self._repo = repo

    @classmethod
    def build(
        cls,
        bus: AgentMessageBus,
        repo: "MessageRepository",
    ) -> "ConsensusConsumer":
        """Factory — no LLM dependencies. consensus.evaluate is a pure function."""
        return cls(bus, repo)

    def start(self) -> None:
        self._bus.subscribe(
            channel=AgentChannels.CRITIQUES,
            consumer_group=ConsumerGroups.CONSENSUS_ENGINE,
            consumer_name=CONSUMER_NAME,
            handler=self._handle_message,
            max_retries=MAX_RETRIES,
        )
        logger.info(
            "ConsensusConsumer subscribed to %s (group=%s, max_retries=%d)",
            AgentChannels.CRITIQUES,
            ConsumerGroups.CONSENSUS_ENGINE,
            MAX_RETRIES,
        )

    def stop(self) -> None:
        logger.info("ConsensusConsumer stopping")

    # ── Handler ───────────────────────────────────────────────────────────────

    def _handle_message(self, message) -> None:
        if not isinstance(message, CritiqueMessage):
            logger.warning(
                "ConsensusConsumer received non-Critique message: %s", type(message)
            )
            return

        critique = message
        corr = critique.correlation_id

        logger.info(
            "ConsensusConsumer evaluating corr=%s critic=%s stance=%s",
            corr, critique.agent_id.value, critique.stance.value,
        )

        # Lookup the proposal from DB (F1: no in-memory cache).
        row = self._repo.get_proposal_by_correlation_id(corr)
        if row is None:
            logger.warning(
                "ConsensusConsumer: no proposal found for corr=%s (stale critique "
                "from DLQ or proposal was deleted); skipping evaluate",
                corr,
            )
            return

        proposal = ProposalMessage.model_validate(row["full_payload"])

        # Sprint 4 N=1: single critique triggers consensus immediately.
        decision = consensus.evaluate(
            proposal=proposal,
            critiques=[critique],
            correlation_id=corr,
        )

        # Persist decision, then advance proposal status.
        self._repo.save_decision(decision)
        self._repo.update_proposal_status(corr, "decided")

        # Publish to bus for AtlasConsumer downstream.
        self._bus.publish(AgentChannels.DECISIONS, decision)

        logger.info(
            "ConsensusConsumer done corr=%s outcome=%s consensus_type=%s contrarian=%s",
            corr,
            decision.outcome.value,
            decision.consensus_state.consensus_type.value,
            decision.contrarian_flag_raised,
        )
