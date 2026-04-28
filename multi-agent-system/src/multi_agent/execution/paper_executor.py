"""
PaperExecutor — executor de paper trading (Nivel 2: slippage simulado).

Comportamiento:
- Recibe AtlasValidationMessage aprobado (approved=True)
- Simula slippage como función del spread bid-ask implícito + IV del activo
- Simula probabilidad baja de partial fills (configurable)
- Construye ExecutionMessage y lo publica al bus
- Escribe a trades.executions vía MessageRepository

Nivel de simulación:
  Nivel 1 (Sprint 1): fill exacto al precio solicitado
  Nivel 2 (Sprint 2A, este módulo): slippage realista, partial fills ocasionales
  Nivel 3 (Sprint 5+): integración con Schwab API paper account
"""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from decimal import Decimal

from ..communication.enums import AgentId, TradeStatus
from ..communication.message_bus import AgentChannels, AgentMessageBus
from ..communication.schemas import (
    AtlasValidationMessage,
    ExecutionMessage,
    FillRecord,
    SlippageInfo,
)

logger = logging.getLogger(__name__)

# ── Slippage parameters ───────────────────────────────────────────────────────
# Slippage como % del precio: base + random noise
# Para opciones: spread más ancho, mayor slippage
_EQUITY_SLIPPAGE_BASE_PCT = 0.02    # 0.02% base slippage para equity
_EQUITY_SLIPPAGE_NOISE_PCT = 0.03   # hasta 0.03% adicional aleatorio
_OPTIONS_SLIPPAGE_BASE_PCT = 0.15   # 0.15% base para opciones (bid-ask más amplio)
_OPTIONS_SLIPPAGE_NOISE_PCT = 0.25  # hasta 0.25% adicional

# Probabilidad de partial fill (por ejecución)
_PARTIAL_FILL_PROBABILITY = 0.08    # 8% de chance de fill parcial

# Rango de fill para partials: se llena entre 60% y 90% del size
_PARTIAL_FILL_MIN_PCT = 0.60
_PARTIAL_FILL_MAX_PCT = 0.90

# Strategies con comportamiento de opciones
_OPTIONS_STRATEGIES = frozenset({
    "CSP", "COVERED_CALL", "CREDIT_SPREAD", "DEBIT_SPREAD",
    "IRON_CONDOR", "LEAP", "CALENDAR", "ZERO_DTE", "WEEKLY",
})


class PaperExecutor:
    """
    Lee AtlasValidationMessage del bus, simula ejecución y publica ExecutionMessage.

    proposal_cache: dict[correlation_id → ProposalMessage] — mismo dict que usa AtlasConsumer.
    """

    def __init__(
        self,
        bus: AgentMessageBus,
        repo,
        proposal_cache: dict | None = None,
        rng_seed: int | None = None,
    ) -> None:
        self._bus = bus
        self._repo = repo
        self._proposal_cache: dict = proposal_cache if proposal_cache is not None else {}
        self._rng = random.Random(rng_seed)

    def start(self) -> None:
        self._bus.subscribe(
            channel=AgentChannels.ATLAS_VALIDATION,
            consumer_group="paper_executor",
            consumer_name="executor-1",
            handler=self._handle_message,
        )
        logger.info("PaperExecutor subscribed to %s", AgentChannels.ATLAS_VALIDATION)

    def stop(self) -> None:
        logger.info("PaperExecutor stopping")

    # ── Handler ───────────────────────────────────────────────────────────────

    def _handle_message(self, message) -> None:
        if not isinstance(message, AtlasValidationMessage):
            return

        atlas = message

        if not atlas.approved:
            logger.info(
                "PaperExecutor: skipping rejected trade corr=%s reason=%s",
                atlas.correlation_id,
                atlas.reason,
            )
            return

        proposal = self._proposal_cache.get(str(atlas.correlation_id))
        if proposal is None:
            logger.error(
                "PaperExecutor: no proposal in cache for corr=%s", atlas.correlation_id
            )
            return

        execution_msg = self._simulate_execution(atlas, proposal)

        # Persist
        try:
            from ..persistence.message_repository import MessageRepository
            if isinstance(self._repo, MessageRepository):
                self._repo.save_execution(execution_msg)
        except Exception:
            logger.exception("PaperExecutor: failed to persist execution (non-fatal)")

        # Publish
        self._bus.publish(AgentChannels.EXECUTION, execution_msg)

        logger.info(
            "PaperExecutor executed corr=%s ticker=%s status=%s",
            atlas.correlation_id,
            proposal.trade.ticker,
            execution_msg.execution_status,
        )

    # ── Simulation ────────────────────────────────────────────────────────────

    def _simulate_execution(
        self,
        atlas: AtlasValidationMessage,
        proposal,
    ) -> ExecutionMessage:
        start_ns = time.monotonic_ns()

        strategy = proposal.trade.strategy_type.value
        is_options = strategy in _OPTIONS_STRATEGIES
        legs = proposal.trade.structure.legs

        fills = []
        all_filled = True

        for i, leg in enumerate(legs):
            expected_price = float(leg.strike)  # use strike as proxy for fill price

            # Slippage
            if is_options:
                slippage_pct = (
                    _OPTIONS_SLIPPAGE_BASE_PCT
                    + self._rng.uniform(0, _OPTIONS_SLIPPAGE_NOISE_PCT)
                ) / 100
            else:
                slippage_pct = (
                    _EQUITY_SLIPPAGE_BASE_PCT
                    + self._rng.uniform(0, _EQUITY_SLIPPAGE_NOISE_PCT)
                ) / 100

            # Slippage direction: adverse (we pay more / receive less)
            # For buy: price goes up; for sell: price goes down
            from ..communication.enums import Direction
            if leg.action == Direction.BUY:
                fill_price = expected_price * (1 + slippage_pct)
            else:
                fill_price = expected_price * (1 - slippage_pct)

            # Partial fill
            qty = leg.quantity
            if self._rng.random() < _PARTIAL_FILL_PROBABILITY:
                fill_fraction = self._rng.uniform(_PARTIAL_FILL_MIN_PCT, _PARTIAL_FILL_MAX_PCT)
                qty = max(1, int(qty * fill_fraction))
                all_filled = False

            fills.append(FillRecord(
                leg=i + 1,
                fill_price=Decimal(str(round(fill_price, 4))),
                fill_quantity=qty,
                fill_timestamp=datetime.now(timezone.utc),
                venue="PAPER",
            ))

        status = TradeStatus.FILLED if all_filled else TradeStatus.PARTIAL

        # Slippage summary (for single-leg simplicity; multi-leg = leg-1)
        expected_credit = proposal.trade.structure.estimated_credit or Decimal("0")
        actual_credit = fills[0].fill_price if fills else Decimal("0")
        slippage_usd = float(actual_credit - expected_credit)
        slippage_info = SlippageInfo(
            expected_credit=expected_credit,
            actual_credit=actual_credit,
            slippage_pct=slippage_usd / float(expected_credit) * 100 if expected_credit else 0.0,
        ) if expected_credit else None

        elapsed_ms = (time.monotonic_ns() - start_ns) // 1_000_000

        return ExecutionMessage(
            agent_id=AgentId.ATLAS,  # executor acts as ATLAS subsystem
            correlation_id=atlas.correlation_id,
            parent_message_id=atlas.message_id,
            execution_status=status,
            fills=fills,
            slippage_vs_proposal=slippage_info,
            execution_time_ms=elapsed_ms,
        )
