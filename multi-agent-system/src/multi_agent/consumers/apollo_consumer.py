"""
ApolloConsumer — consumer Redis Streams para Sprint 4 B.4.5a.

Flujo:
  1. Lee ProposalMessage del stream agent.proposals.
  2. Update trades.proposals.status → 'under_critique'.
  3. Snapshot market_state via data_layer.
  4. Call ApolloAgent.critique_proposal(proposal, market_state, correlation_id).
  5. Persiste CritiqueMessage en DB.
  6. Publica CritiqueMessage al stream agent.critiques.

Error handling: handler exceptions bubble to AgentMessageBus, which retries
up to max_retries=2 (decisión K3 de B.4.5) and then sends to DLQ. NO retry
logic in the consumer itself.

El consumer corre como daemon thread dentro de AgentMessageBus.
Para iniciar: consumer.start() → consumer.stop().
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..agents.apollo_agent import ApolloAgent
from ..communication.message_bus import AgentChannels, AgentMessageBus, ConsumerGroups
from ..communication.schemas import ProposalMessage

if TYPE_CHECKING:
    from claude_router.router import ClaudeRouter
    from ..data_layer import DataLayer
    from ..persistence.message_repository import MessageRepository

logger = logging.getLogger(__name__)

CONSUMER_NAME = "apollo-1"
MAX_RETRIES = 2


class ApolloConsumer:
    """
    Wires AgentMessageBus.PROPOSALS → ApolloAgent.critique_proposal →
    save_critique → publish to CRITIQUES.

    Subscribes to the agent.proposals stream with consumer_group=CRITIQUE_ENGINE
    and max_retries=2 (K3). On a handler exception, the bus retries twice,
    then routes the message to the dead-letter stream.

    Per ADR-003 D7.2, this is the only critic agent in Sprint 4. Future
    sprints add HERMES/NYX/VESTA — each will subscribe to PROPOSALS with
    its own consumer_name to fan out via Redis Streams consumer groups.
    """

    def __init__(
        self,
        bus: AgentMessageBus,
        repo: "MessageRepository",
        apollo_agent: ApolloAgent,
        data_layer: "DataLayer",
    ) -> None:
        self._bus = bus
        self._repo = repo
        self._apollo_agent = apollo_agent
        self._data_layer = data_layer

    @classmethod
    def build(
        cls,
        bus: AgentMessageBus,
        repo: "MessageRepository",
        claude_router: "ClaudeRouter",
        data_layer: "DataLayer",
    ) -> "ApolloConsumer":
        """Factory — instantiates ApolloAgent from claude_router."""
        apollo_agent = ApolloAgent(claude_router)
        return cls(bus, repo, apollo_agent, data_layer)

    def start(self) -> None:
        self._bus.subscribe(
            channel=AgentChannels.PROPOSALS,
            consumer_group=ConsumerGroups.CRITIQUE_ENGINE,
            consumer_name=CONSUMER_NAME,
            handler=self._handle_message,
            max_retries=MAX_RETRIES,
        )
        logger.info(
            "ApolloConsumer subscribed to %s (group=%s, max_retries=%d)",
            AgentChannels.PROPOSALS,
            ConsumerGroups.CRITIQUE_ENGINE,
            MAX_RETRIES,
        )

    def stop(self) -> None:
        logger.info("ApolloConsumer stopping")

    # ── Handler ───────────────────────────────────────────────────────────────

    def _handle_message(self, message) -> None:
        if not isinstance(message, ProposalMessage):
            logger.warning("ApolloConsumer received non-Proposal message: %s", type(message))
            return

        proposal = message
        corr = proposal.correlation_id

        logger.info(
            "ApolloConsumer critiquing corr=%s ticker=%s",
            corr, proposal.trade.ticker,
        )

        # Status: under_critique (visible to dashboard polling).
        self._repo.update_proposal_status(corr, "under_critique")

        # Snapshot market state for APOLLO's macro lens.
        market_state = self._data_layer.snapshot()

        # APOLLO LLM call (5-15s typical).
        critique = self._apollo_agent.critique_proposal(
            proposal=proposal,
            market_state=market_state,
            correlation_id=corr,
        )

        # Persist + publish.
        self._repo.save_critique(critique)
        self._bus.publish(AgentChannels.CRITIQUES, critique)

        logger.info(
            "ApolloConsumer done corr=%s stance=%s veto=%s contrarian=%s",
            corr,
            critique.stance.value,
            critique.veto_request,
            critique.contrarian_flag_raised,
        )
