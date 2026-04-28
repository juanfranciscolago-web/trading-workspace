"""
AtlasConsumer — consumer Redis Streams que reemplaza al MockOrchestrator sincrónico.

Flujo:
  1. Lee DecisionMessage del stream agent.decisions
  2. Construye PortfolioSnapshot (con cache TTL 5s)
  3. Llama a atlas_core.validate() (fail-closed garantizado)
  4. Persiste AtlasValidationMessage + atlas_snapshot en la DB
  5. Publica AtlasValidationMessage al stream agent.atlas_validations
  6. Si approved=False → también escribe a trades.rejected_dlq

El consumer corre como daemon thread dentro de AgentMessageBus.
Para iniciar: consumer.start() → consumer.stop()
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..communication.enums import AgentId
from ..communication.message_bus import AgentChannels, AgentMessageBus, ConsumerGroups
from ..communication.schemas import DecisionMessage, ProposalMessage
from ..risk import atlas_validate, load_buckets, load_limits
from ..risk.portfolio_snapshot import CachedSnapshotBuilder, SnapshotBuilder

if TYPE_CHECKING:
    from ..persistence.message_repository import MessageRepository

logger = logging.getLogger(__name__)

CONSUMER_NAME = "atlas-1"


class AtlasConsumer:
    """
    Wires AgentMessageBus → atlas_core → MessageRepository → bus publish.

    proposal_cache: dict[correlation_id → ProposalMessage] para poder
    pasar la propuesta original a atlas_core (necesita el ticker, sizing, etc.).
    El consumer de proposals alimenta este cache simultáneamente.
    """

    def __init__(
        self,
        bus: AgentMessageBus,
        repo: "MessageRepository",
        snapshot_builder: CachedSnapshotBuilder,
        proposal_cache: dict | None = None,
    ) -> None:
        self._bus = bus
        self._repo = repo
        self._snapshot_builder = snapshot_builder
        self._proposal_cache: dict = proposal_cache if proposal_cache is not None else {}
        self._limits = load_limits()
        self._buckets = load_buckets()

    @classmethod
    def build(
        cls,
        bus: AgentMessageBus,
        repo: "MessageRepository",
        pool,
        proposal_cache: dict | None = None,
    ) -> "AtlasConsumer":
        """Factory — builds CachedSnapshotBuilder from pool."""
        builder = CachedSnapshotBuilder(SnapshotBuilder(pool))
        return cls(bus, repo, builder, proposal_cache)

    def start(self) -> None:
        self._bus.subscribe(
            channel=AgentChannels.DECISIONS,
            consumer_group=ConsumerGroups.ATLAS_VALIDATOR,
            consumer_name=CONSUMER_NAME,
            handler=self._handle_message,
        )
        logger.info("AtlasConsumer subscribed to %s", AgentChannels.DECISIONS)

    def stop(self) -> None:
        logger.info("AtlasConsumer stopping")

    # ── Handler ───────────────────────────────────────────────────────────────

    def _handle_message(self, message) -> None:
        if not isinstance(message, DecisionMessage):
            logger.warning("AtlasConsumer received non-Decision message: %s", type(message))
            return

        decision = message
        corr = decision.correlation_id

        proposal = self._proposal_cache.get(str(corr))
        if proposal is None:
            logger.error(
                "No proposal in cache for corr=%s — cannot validate (reject fail-closed)",
                corr,
            )
            return

        logger.info(
            "AtlasConsumer validating corr=%s ticker=%s outcome=%s",
            corr,
            proposal.trade.ticker,
            decision.outcome,
        )

        snapshot = self._snapshot_builder.get()

        atlas_msg = atlas_validate(
            proposal=proposal,
            decision=decision,
            snapshot=snapshot,
            limits=self._limits,
            buckets=self._buckets,
        )

        # Persist snapshot to atlas.portfolio_snapshots
        try:
            positions_serializable = [
                {
                    "ticker": p.ticker,
                    "asset_class": p.asset_class,
                    "quantity": p.quantity,
                    "market_value_usd": float(p.market_value_usd),
                    "delta": float(p.delta),
                    "vega": float(p.vega),
                }
                for p in snapshot.positions
            ]
            self._repo.save_atlas_snapshot(
                snapshot_id=snapshot.snapshot_id,
                snapshot_at=snapshot.snapshot_at,
                nav_usd=float(snapshot.nav_usd),
                cash_usd=float(snapshot.cash_usd),
                buying_power_used_pct=snapshot.buying_power_used_pct,
                portfolio_beta=snapshot.portfolio_beta,
                vega_total=snapshot.vega_total,
                pnl_daily_usd=float(snapshot.pnl_daily_usd),
                drawdown_from_peak_pct=snapshot.drawdown_from_peak_pct,
                positions=positions_serializable,
            )
        except Exception:
            logger.exception("Failed to persist atlas snapshot (non-fatal) corr=%s", corr)

        # Persist atlas validation message
        self._repo.save_atlas_validation(atlas_msg)

        # Publish to bus
        self._bus.publish(AgentChannels.ATLAS_VALIDATION, atlas_msg)

        # If rejected, write to DLQ table
        if not atlas_msg.approved:
            try:
                self._repo.save_rejected_dlq(
                    source="atlas_rejection",
                    correlation_id=corr,
                    ticker=proposal.trade.ticker,
                    proposing_agent=proposal.agent_id.value.lower(),
                    reason=atlas_msg.reason,
                    original_channel=AgentChannels.DECISIONS,
                    dlq_entry_id=None,
                    payload=atlas_msg.model_dump(mode="json"),
                    atlas_version=atlas_msg.atlas_version,
                )
            except Exception:
                logger.exception("Failed to save rejected_dlq (non-fatal) corr=%s", corr)

        log_status = "APPROVED" if atlas_msg.approved else f"REJECTED ({atlas_msg.reason})"
        logger.info(
            "AtlasConsumer done corr=%s status=%s executed_size=%s ms=%.1f",
            corr,
            log_status,
            atlas_msg.executed_size,
            atlas_msg.evaluation_time_ms,
        )

    # ── Proposal cache management ─────────────────────────────────────────────

    def cache_proposal(self, proposal: ProposalMessage) -> None:
        """Register a proposal so it can be looked up when its Decision arrives."""
        self._proposal_cache[str(proposal.correlation_id)] = proposal

    def evict_proposal(self, correlation_id) -> None:
        self._proposal_cache.pop(str(correlation_id), None)
