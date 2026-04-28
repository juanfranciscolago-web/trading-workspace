"""
ATLAS core — orquesta los 8 checks y construye AtlasValidationMessage.

Este módulo es la pieza más crítica del sistema: un bug acá puede aprobar
trades que deberían bloquearse. Tests exhaustivos en tests/risk/test_atlas_core.py.

Principio fail-closed: cualquier excepción interna → reject explícito.
Nunca se propaga una excepción hacia arriba — el consumer siempre recibe un resultado.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any

from ..communication.enums import AgentId, AtlasReason, RiskMode, StrategyType
from ..communication.schemas import AtlasValidationMessage, DecisionMessage, ProposalMessage
from .checks import (
    CheckResult,
    check_beta,
    check_bucket_saturation,
    check_buying_power,
    check_kill_switches,
    check_pnl_halt,
    check_sector_saturation,
    check_single_name,
    check_vega,
)
from .config import BucketConfig, Phase1Limits
from .portfolio_snapshot import PortfolioSnapshot

logger = logging.getLogger(__name__)

ATLAS_VERSION = "atlas-mvp-1.0"

# Strategies that involve options (have vega exposure)
_OPTIONS_STRATEGIES = frozenset({
    StrategyType.CSP,
    StrategyType.COVERED_CALL,
    StrategyType.CREDIT_SPREAD,
    StrategyType.DEBIT_SPREAD,
    StrategyType.IRON_CONDOR,
    StrategyType.LEAP,
    StrategyType.CALENDAR,
    StrategyType.ZERO_DTE,
    StrategyType.WEEKLY,
})


def validate(
    proposal: ProposalMessage,
    decision: DecisionMessage,
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
    buckets: BucketConfig,
) -> AtlasValidationMessage:
    """
    Entry point público de ATLAS core.

    Fail-closed: si ocurre cualquier excepción interna durante la validación,
    retorna un AtlasValidationMessage con approved=False y reason=REJECTED_SYSTEM_ERROR.
    Nunca lanza hacia el caller.
    """
    start = time.monotonic()

    try:
        result = _validate_internal(proposal, decision, snapshot, limits, buckets)
    except Exception as exc:
        logger.exception(
            "ATLAS core exception — fail-closed reject. corr=%s error=%s",
            proposal.correlation_id,
            exc,
        )
        elapsed = (time.monotonic() - start) * 1000
        return _build_fail_closed(proposal, decision, snapshot, elapsed)

    elapsed = (time.monotonic() - start) * 1000
    result["evaluation_time_ms"] = elapsed
    return AtlasValidationMessage(**result)


# ── Internal ──────────────────────────────────────────────────────────────────

def _validate_internal(
    proposal: ProposalMessage,
    decision: DecisionMessage,
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
    buckets: BucketConfig,
) -> dict[str, Any]:
    """
    Core validation logic. Returns dict of kwargs for AtlasValidationMessage.
    Raises on unexpected errors (caught by validate()).
    """
    ticker = proposal.trade.ticker
    strategy_type = proposal.trade.strategy_type
    proposed_size_pct = Decimal(str(proposal.sizing.proposed_size_pct_portfolio))
    buying_power_req = proposal.trade.structure.buying_power_required
    is_options = strategy_type in _OPTIONS_STRATEGIES

    # Sprint 2A: estimated trade metrics (real Greeks in Sprint 3+ from data layer)
    # equity/sector_rotation: full beta contribution, no vega
    # options strategies: partial beta (delta exposure), negative vega (short)
    beta_per_pct = 0.5 if is_options else 1.0
    proposed_beta_addition = float(proposed_size_pct) * beta_per_pct
    # vega estimate: -500 USD per VIX point per % portfolio (short options typical)
    proposed_vega_addition = float(proposed_size_pct) * (-500.0) if is_options else 0.0

    checks_passed: list[str] = []
    checks_failed: list[str] = []
    all_metrics: dict[str, Any] = {}
    max_sizes: list[Decimal] = []  # collected from reductive checks
    rejected = False
    final_reason = AtlasReason.APPROVED

    def _run(name: str, result: CheckResult) -> bool:
        """Record check result; return False if it triggered a rejection."""
        all_metrics.update(result.metrics)
        if not result.passed:
            # Hard rejection: kill switch (max=None) or at-limit reductive (max=0)
            checks_failed.append(name)
            return False
        # Passed — may carry a size restriction
        if result.max_allowed_size is not None and result.max_allowed_size > Decimal("0"):
            max_sizes.append(result.max_allowed_size)
        checks_passed.append(name)
        return True

    # ── Rejection-only checks (fail-fast) ──────────────────────────────────────

    r = check_kill_switches(snapshot, limits)
    if not _run("kill_switches", r):
        rejected = True
        final_reason = r.reason

    if not rejected:
        r = check_pnl_halt(snapshot, limits)
        if not _run("pnl_halt", r):
            rejected = True
            final_reason = r.reason

    if not rejected:
        r = check_buying_power(buying_power_req, snapshot, limits)
        if not _run("buying_power", r):
            rejected = True
            final_reason = r.reason

    # ── Reductive checks (continue even if prior check reduced size) ───────────

    if not rejected:
        r = check_single_name(ticker, proposed_size_pct, snapshot, limits)
        if not _run("single_name", r):
            rejected = True
            final_reason = r.reason

    if not rejected:
        r = check_sector_saturation(ticker, proposed_size_pct, snapshot, limits, buckets)
        if not _run("sector_saturation", r):
            rejected = True
            final_reason = r.reason

    if not rejected:
        r = check_bucket_saturation(ticker, proposed_size_pct, snapshot, limits, buckets)
        if not _run("bucket_saturation", r):
            rejected = True
            final_reason = r.reason

    if not rejected:
        r = check_beta(proposed_beta_addition, snapshot, limits)
        if not _run("beta", r):
            rejected = True
            final_reason = r.reason
        elif "beta_size_fraction_allowed" in r.metrics:
            frac = Decimal(str(r.metrics["beta_size_fraction_allowed"]))
            max_sizes.append(proposed_size_pct * frac)

    if not rejected and is_options:
        r = check_vega(proposed_vega_addition, proposed_size_pct, snapshot, limits)
        if not _run("vega", r):
            rejected = True
            final_reason = r.reason

    # ── Compute executed_size ─────────────────────────────────────────────────

    if rejected:
        executed_size = Decimal("0")
    elif max_sizes:
        executed_size = min(max_sizes)
        # Clamp: never execute more than proposed, never negative
        executed_size = max(Decimal("0"), min(executed_size, proposed_size_pct))
    else:
        executed_size = proposed_size_pct

    approved = not rejected and executed_size > Decimal("0")

    # ── Risk mode ─────────────────────────────────────────────────────────────

    risk_mode = _compute_risk_mode(snapshot, limits, rejected)
    all_metrics["portfolio.risk_mode"] = risk_mode.value

    # ── Stress tests ──────────────────────────────────────────────────────────

    stress = _compute_stress_tests(snapshot, proposal)
    all_metrics.update(stress)

    return dict(
        agent_id=AgentId.ATLAS,
        correlation_id=proposal.correlation_id,
        parent_message_id=decision.message_id,
        atlas_version=ATLAS_VERSION,
        approved=approved,
        executed_size=executed_size,
        original_size=proposed_size_pct,
        reason=final_reason,
        risk_mode=risk_mode,
        checks_passed=checks_passed,
        checks_failed=checks_failed,
        metrics_snapshot=all_metrics,
        portfolio_snapshot_id=snapshot.snapshot_id,
        evaluation_time_ms=0.0,  # replaced by caller
    )


def _compute_risk_mode(
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
    rejected: bool,
) -> RiskMode:
    """
    Determina el modo operacional de ATLAS basado en el estado del portfolio.

    GREEN:  Todo dentro de límites normales
    YELLOW: Drawdown entre halt y kill switch, o buying power elevado
    RED:    Drawdown en zona de halt activo
    BLACK:  Kill switch activado (no debería llegar acá — ya rechazamos antes)
    """
    dd = snapshot.drawdown_from_peak_pct
    bp = snapshot.buying_power_used_pct

    kill_dd = limits.pnl.drawdown_kill_switch_pct
    halt_dd = limits.pnl.drawdown_halt_pct
    bp_limit = limits.buying_power.normal_max_pct

    if dd <= kill_dd:
        return RiskMode.BLACK
    if dd <= halt_dd:
        return RiskMode.RED
    if dd <= halt_dd * 0.6 or bp >= bp_limit * 0.85:
        return RiskMode.YELLOW
    return RiskMode.GREEN


def _compute_stress_tests(
    snapshot: PortfolioSnapshot,
    proposal: ProposalMessage,
) -> dict[str, Any]:
    """
    Sprint 2A: dos stress tests básicos usando estimaciones simples.
    Sprint 3+: stress tests con Greeks reales y escenarios históricos.

    SPX -5%: pérdida ≈ portfolio_beta * 5% * NAV
    VIX +30%: pérdida ≈ |vega_total| * 30 * factor
    """
    nav = float(snapshot.nav_usd)
    beta = snapshot.portfolio_beta
    vega = snapshot.vega_total  # negativo = short vega

    # SPX -5%
    spx_impact_pct = -(beta * 5.0)  # rough: portfolio moves beta * index
    spx_impact_usd = nav * spx_impact_pct / 100

    # VIX +30pt: vega loss = vega_total * 30 (vega is $ per VIX point)
    # Short vega (negative) means we lose when VIX goes up
    vix_impact_usd = vega * 30.0  # already in $; negative = loss for short vega
    vix_impact_pct = vix_impact_usd / nav * 100 if nav else 0.0

    return {
        "stress.spx_down_5pct": {
            "impact_usd": round(spx_impact_usd, 2),
            "impact_pct": round(spx_impact_pct, 4),
            "assumption": "portfolio_beta_x_5pct_index_move",
        },
        "stress.vix_spike_30pct": {
            "impact_usd": round(vix_impact_usd, 2),
            "impact_pct": round(vix_impact_pct, 4),
            "assumption": "vega_total_x_30_vix_points",
        },
    }


def _build_fail_closed(
    proposal: ProposalMessage,
    decision: DecisionMessage,
    snapshot: PortfolioSnapshot,
    elapsed_ms: float,
) -> AtlasValidationMessage:
    """Construye un reject explícito cuando ATLAS crashea internamente."""
    return AtlasValidationMessage(
        agent_id=AgentId.ATLAS,
        correlation_id=proposal.correlation_id,
        parent_message_id=decision.message_id,
        atlas_version=ATLAS_VERSION,
        approved=False,
        executed_size=Decimal("0"),
        original_size=Decimal(str(proposal.sizing.proposed_size_pct_portfolio)),
        reason=AtlasReason.REJECTED_SYSTEM_ERROR,
        risk_mode=RiskMode.RED,
        checks_passed=[],
        checks_failed=["system_error"],
        metrics_snapshot={"error": "atlas_core_exception"},
        portfolio_snapshot_id=snapshot.snapshot_id,
        evaluation_time_ms=elapsed_ms,
    )
