"""
ATLAS check functions — lógica pura, sin I/O.

Cada función retorna un CheckResult con:
  - passed: bool
  - max_allowed_size: Decimal | None  (None = check no restringe tamaño)
  - reason: str  (AtlasReason constant)
  - metrics: dict  (va al metrics_snapshot del mensaje)

Orden de ejecución (definido en atlas_core.py):
  1. check_kill_switches     — rejection-only
  2. check_pnl_halt          — rejection-only
  3. check_buying_power      — rejection-only
  4. check_single_name       — reductive (puede reducir)
  5. check_sector_saturation — reductive
  6. check_bucket_saturation — reductive
  7. check_beta              — reductive
  8. check_vega              — reductive (solo si la propuesta tiene opciones)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..communication.enums import AtlasReason
from .config import BucketConfig, Phase1Limits
from .portfolio_snapshot import PortfolioSnapshot


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class CheckResult:
    passed: bool
    max_allowed_size: Decimal | None    # None = no size restriction from this check
    reason: str                         # AtlasReason constant
    metrics: dict[str, Any] = field(default_factory=dict)


# ── 1. Kill switches ─────────────────────────────────────────────────────────

def check_kill_switches(
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
) -> CheckResult:
    """
    Checks absolutamente no negociables.
    - Drawdown desde peak > kill_switch_pct → halt total
    - Pérdida en el día > daily_loss_kill_switch_pct → halt total
    """
    dd = snapshot.drawdown_from_peak_pct
    daily_pct = snapshot.pnl_daily_pct

    kill_dd = limits.pnl.drawdown_kill_switch_pct       # ej. -25.0
    kill_daily = limits.pnl.daily_loss_kill_switch_pct  # ej. -8.0

    metrics = {
        "limits.drawdown_kill_switch_pct": kill_dd,
        "limits.daily_loss_kill_switch_pct": kill_daily,
        "portfolio.drawdown_from_peak_pct": dd,
        "portfolio.pnl_daily_pct": daily_pct,
    }

    if dd <= kill_dd:
        return CheckResult(
            passed=False,
            max_allowed_size=None,
            reason=AtlasReason.REJECTED_KILL_SWITCH,
            metrics={**metrics, "trigger": "drawdown_kill_switch", "value": dd, "limit": kill_dd},
        )

    if daily_pct <= kill_daily:
        return CheckResult(
            passed=False,
            max_allowed_size=None,
            reason=AtlasReason.REJECTED_KILL_SWITCH,
            metrics={**metrics, "trigger": "daily_loss_kill_switch", "value": daily_pct, "limit": kill_daily},
        )

    return CheckResult(passed=True, max_allowed_size=None, reason=AtlasReason.APPROVED, metrics=metrics)


# ── 2. PnL halts ──────────────────────────────────────────────────────────────

def check_pnl_halt(
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
) -> CheckResult:
    """
    Halts operacionales (no kill switch).
    - Pérdida diaria > daily_halt_pct
    - Pérdida semanal > weekly_halt_pct
    - Drawdown desde peak > drawdown_halt_pct (zona de alerta, no kill switch)
    """
    daily_pct = snapshot.pnl_daily_pct
    weekly_pct = snapshot.pnl_weekly_pct
    dd = snapshot.drawdown_from_peak_pct

    daily_limit = limits.pnl.daily_halt_pct       # ej. -2.5
    weekly_limit = limits.pnl.weekly_halt_pct     # ej. -4.0
    dd_limit = limits.pnl.drawdown_halt_pct       # ej. -12.0

    metrics = {
        "limits.daily_halt_pct": daily_limit,
        "limits.weekly_halt_pct": weekly_limit,
        "limits.drawdown_halt_pct": dd_limit,
        "portfolio.pnl_daily_pct": daily_pct,
        "portfolio.pnl_weekly_pct": weekly_pct,
        "portfolio.drawdown_from_peak_pct": dd,
    }

    if daily_pct <= daily_limit:
        return CheckResult(
            passed=False,
            max_allowed_size=None,
            reason=AtlasReason.REJECTED_PNL_HALT_DAILY,
            metrics={**metrics, "trigger": "daily_halt", "value": daily_pct},
        )

    if weekly_pct <= weekly_limit:
        return CheckResult(
            passed=False,
            max_allowed_size=None,
            reason=AtlasReason.REJECTED_PNL_HALT_WEEKLY,
            metrics={**metrics, "trigger": "weekly_halt", "value": weekly_pct},
        )

    if dd <= dd_limit:
        return CheckResult(
            passed=False,
            max_allowed_size=None,
            reason=AtlasReason.REJECTED_DRAWDOWN_HALT,
            metrics={**metrics, "trigger": "drawdown_halt", "value": dd},
        )

    return CheckResult(passed=True, max_allowed_size=None, reason=AtlasReason.APPROVED, metrics=metrics)


# ── 3. Buying power ───────────────────────────────────────────────────────────

def check_buying_power(
    proposed_bp_required_usd: Decimal,
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
    *,
    macro_event_active: bool = False,
) -> CheckResult:
    """
    Verifica que la operación no supere el límite de buying power.

    proposed_bp_required_usd: buying_power_required del proposal (en USD).
    macro_event_active: True si hay evento de calendario próximo (FOMC, NFP, CPI).
    Sprint 2A: macro_event_active siempre False (calendar integration = Sprint 3+).
    """
    nav = float(snapshot.nav_usd)
    current_bp_pct = snapshot.buying_power_used_pct
    proposal_bp_pct = float(proposed_bp_required_usd) / nav * 100 if nav else 0.0
    post_bp_pct = current_bp_pct + proposal_bp_pct

    limit = limits.buying_power.macro_event_max_pct if macro_event_active else limits.buying_power.normal_max_pct

    metrics = {
        "limits.buying_power_max_pct": limit,
        "portfolio.buying_power_used_pct": current_bp_pct,
        "exposure.proposal_bp_pct": proposal_bp_pct,
        "exposure.post_trade_bp_pct": post_bp_pct,
    }

    if post_bp_pct > limit:
        return CheckResult(
            passed=False,
            max_allowed_size=None,
            reason=AtlasReason.REJECTED_BP_INSUFFICIENT,
            metrics={**metrics, "excess_pct": post_bp_pct - limit},
        )

    return CheckResult(passed=True, max_allowed_size=None, reason=AtlasReason.APPROVED, metrics=metrics)


# ── 4. Single name ────────────────────────────────────────────────────────────

def check_single_name(
    ticker: str,
    proposed_size_pct: Decimal,
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
) -> CheckResult:
    """
    Límite máximo de exposición a un solo ticker.
    Si el trade llevaría la exposición por encima del límite, reduce el tamaño.
    """
    current_pct = Decimal(str(snapshot.exposure_pct(ticker)))
    post_pct = current_pct + proposed_size_pct
    limit = Decimal(str(limits.exposure.single_name_max_pct))

    metrics = {
        "limits.single_name_max_pct": float(limit),
        "exposure.current_pct": float(current_pct),
        "exposure.proposed_addition_pct": float(proposed_size_pct),
        "exposure.post_trade_pct": float(post_pct),
        "exposure.ticker": ticker,
    }

    if post_pct <= limit:
        return CheckResult(passed=True, max_allowed_size=None, reason=AtlasReason.APPROVED, metrics=metrics)

    max_addition = limit - current_pct
    if max_addition <= Decimal("0"):
        # Already at or over limit — reject entirely
        return CheckResult(
            passed=False,
            max_allowed_size=Decimal("0"),
            reason=AtlasReason.SIZE_REDUCED_POSITION_LIMIT,
            metrics={**metrics, "max_allowed_addition_pct": 0.0},
        )

    return CheckResult(
        passed=True,
        max_allowed_size=max_addition,
        reason=AtlasReason.SIZE_REDUCED_POSITION_LIMIT,
        metrics={**metrics, "max_allowed_addition_pct": float(max_addition)},
    )


# ── 5. Sector saturation ──────────────────────────────────────────────────────

def check_sector_saturation(
    ticker: str,
    proposed_size_pct: Decimal,
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
    buckets: BucketConfig,
) -> CheckResult:
    """
    Límite de exposición a un sector/bucket (30%).
    Tickers en el bucket 'other' no tienen límite de sector.
    """
    bucket_name = buckets.bucket_for(ticker)

    if bucket_name == "other":
        return CheckResult(
            passed=True,
            max_allowed_size=None,
            reason=AtlasReason.APPROVED,
            metrics={"exposure.sector": "other", "exposure.sector_check": "skipped"},
        )

    tickers_in_sector = buckets.tickers_in_bucket(bucket_name)
    current_sector_pct = Decimal(str(snapshot.sector_exposure_pct(tickers_in_sector)))
    post_sector_pct = current_sector_pct + proposed_size_pct
    limit = Decimal(str(limits.exposure.sector_max_pct))

    metrics = {
        "limits.sector_max_pct": float(limit),
        "exposure.sector": bucket_name,
        "exposure.sector_current_pct": float(current_sector_pct),
        "exposure.sector_post_trade_pct": float(post_sector_pct),
    }

    if post_sector_pct <= limit:
        return CheckResult(passed=True, max_allowed_size=None, reason=AtlasReason.APPROVED, metrics=metrics)

    max_addition = limit - current_sector_pct
    if max_addition <= Decimal("0"):
        return CheckResult(
            passed=False,
            max_allowed_size=Decimal("0"),
            reason=AtlasReason.SIZE_REDUCED_BUCKET_LIMIT,
            metrics={**metrics, "max_allowed_addition_pct": 0.0},
        )

    return CheckResult(
        passed=True,
        max_allowed_size=max_addition,
        reason=AtlasReason.SIZE_REDUCED_BUCKET_LIMIT,
        metrics={**metrics, "max_allowed_addition_pct": float(max_addition)},
    )


# ── 6. Bucket saturation (cap absoluto 45%) ───────────────────────────────────

def check_bucket_saturation(
    ticker: str,
    proposed_size_pct: Decimal,
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
    buckets: BucketConfig,
) -> CheckResult:
    """
    Cap absoluto de defensa en profundidad (45%).
    En operación normal el check_sector_saturation (30%) ya reduce antes.
    Este check actúa como backstop si se llegara a superar el 30% (ej. múltiples
    trades parciales aprobados antes de que el snapshot se actualice).
    Tickers en 'other' no tienen límite de bucket.
    """
    bucket_name = buckets.bucket_for(ticker)

    if bucket_name == "other":
        return CheckResult(
            passed=True,
            max_allowed_size=None,
            reason=AtlasReason.APPROVED,
            metrics={"exposure.bucket": "other", "exposure.bucket_check": "skipped"},
        )

    tickers_in_bucket = buckets.tickers_in_bucket(bucket_name)
    current_bucket_pct = Decimal(str(snapshot.sector_exposure_pct(tickers_in_bucket)))
    post_bucket_pct = current_bucket_pct + proposed_size_pct
    limit = Decimal(str(limits.exposure.bucket_max_pct))

    metrics = {
        "limits.bucket_max_pct": float(limit),
        "exposure.bucket": bucket_name,
        "exposure.bucket_current_pct": float(current_bucket_pct),
        "exposure.bucket_post_trade_pct": float(post_bucket_pct),
    }

    if post_bucket_pct <= limit:
        return CheckResult(passed=True, max_allowed_size=None, reason=AtlasReason.APPROVED, metrics=metrics)

    max_addition = limit - current_bucket_pct
    if max_addition <= Decimal("0"):
        return CheckResult(
            passed=False,
            max_allowed_size=Decimal("0"),
            reason=AtlasReason.SIZE_REDUCED_BUCKET_LIMIT,
            metrics={**metrics, "max_allowed_addition_pct": 0.0},
        )

    return CheckResult(
        passed=True,
        max_allowed_size=max_addition,
        reason=AtlasReason.SIZE_REDUCED_BUCKET_LIMIT,
        metrics={**metrics, "max_allowed_addition_pct": float(max_addition)},
    )


# ── 7. Beta ───────────────────────────────────────────────────────────────────

def check_beta(
    proposed_beta_addition: float,
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
) -> CheckResult:
    """
    Mantiene el beta neto del portfolio dentro del rango [-0.3, +1.3].

    proposed_beta_addition: contribución estimada de la nueva posición al beta del portfolio.
    Estimada por atlas_core desde el tipo de estrategia y el tamaño.

    Si el post-trade beta está fuera del rango, computa el máximo tamaño permitido
    que mantiene el beta dentro del límite.
    """
    current_beta = snapshot.portfolio_beta
    beta_min = limits.exposure.beta_min
    beta_max = limits.exposure.beta_max

    metrics = {
        "limits.beta_min": beta_min,
        "limits.beta_max": beta_max,
        "portfolio.beta_current": current_beta,
        "exposure.proposed_beta_addition": proposed_beta_addition,
    }

    if proposed_beta_addition == 0.0:
        return CheckResult(
            passed=True,
            max_allowed_size=None,
            reason=AtlasReason.APPROVED,
            metrics={**metrics, "portfolio.beta_post": current_beta},
        )

    post_beta = current_beta + proposed_beta_addition

    metrics["portfolio.beta_post"] = post_beta

    if beta_min <= post_beta <= beta_max:
        return CheckResult(passed=True, max_allowed_size=None, reason=AtlasReason.APPROVED, metrics=metrics)

    # Compute the fraction of the trade that keeps beta in range
    if proposed_beta_addition > 0:
        # Adding positive beta — cap at beta_max
        headroom = beta_max - current_beta
    else:
        # Adding negative beta — floor at beta_min
        headroom = current_beta - beta_min  # positive if current > beta_min

    if headroom <= 0:
        # Already at or past limit — zero size
        return CheckResult(
            passed=False,
            max_allowed_size=Decimal("0"),
            reason=AtlasReason.SIZE_REDUCED_BETA_LIMIT,
            metrics={**metrics, "headroom_beta": headroom},
        )

    # max_size_fraction = headroom / abs(proposed_beta_addition_per_unit_size)
    # Since proposed_beta_addition IS for the proposed_size_pct, the fraction allowed is:
    fraction_allowed = headroom / abs(proposed_beta_addition)
    fraction_capped = min(fraction_allowed, 1.0)

    return CheckResult(
        passed=True,
        max_allowed_size=None,  # caller must multiply fraction by proposed_size
        reason=AtlasReason.SIZE_REDUCED_BETA_LIMIT,
        metrics={
            **metrics,
            "headroom_beta": headroom,
            "beta_size_fraction_allowed": fraction_capped,
        },
    )


# ── 8. Vega ───────────────────────────────────────────────────────────────────

def check_vega(
    proposed_vega_addition: float,
    proposed_size_pct: Decimal,
    snapshot: PortfolioSnapshot,
    limits: Phase1Limits,
) -> CheckResult:
    """
    Mantiene el vega neto del portfolio dentro del límite.

    Límite: abs(vega_total) ≤ nav_usd * vega_limit_pct_per_vix_point / 100
    (Sprint 2A: vega_limit_pct_per_vix_point = 3%, equivale a 3% del NAV por punto de VIX)

    proposed_vega_addition: vega total de la nueva posición (negativo = short vega).
    Si la propuesta no tiene opciones, proposed_vega_addition = 0 y este check
    siempre pasa.
    """
    if proposed_vega_addition == 0.0:
        return CheckResult(
            passed=True,
            max_allowed_size=None,
            reason=AtlasReason.APPROVED,
            metrics={"exposure.vega_check": "skipped_no_options"},
        )

    nav = float(snapshot.nav_usd)
    vega_limit_abs = nav * limits.greeks.vega_limit_pct_per_vix_point / 100
    current_vega = snapshot.vega_total
    post_vega = current_vega + proposed_vega_addition

    metrics = {
        "limits.vega_abs_limit_usd": vega_limit_abs,
        "portfolio.vega_total_current": current_vega,
        "exposure.proposed_vega_addition": proposed_vega_addition,
        "portfolio.vega_total_post": post_vega,
    }

    # Limit applies to the absolute value (both long and short vega are capped)
    if abs(post_vega) <= vega_limit_abs:
        return CheckResult(passed=True, max_allowed_size=None, reason=AtlasReason.APPROVED, metrics=metrics)

    # Compute headroom
    vega_headroom = vega_limit_abs - abs(current_vega)
    if vega_headroom <= 0:
        return CheckResult(
            passed=False,
            max_allowed_size=Decimal("0"),
            reason=AtlasReason.SIZE_REDUCED_VEGA_LIMIT,
            metrics={**metrics, "vega_headroom": vega_headroom},
        )

    # Fraction of trade allowed
    fraction_allowed = vega_headroom / abs(proposed_vega_addition)
    fraction_capped = min(fraction_allowed, 1.0)
    max_size = proposed_size_pct * Decimal(str(round(fraction_capped, 6)))

    return CheckResult(
        passed=True,
        max_allowed_size=max_size,
        reason=AtlasReason.SIZE_REDUCED_VEGA_LIMIT,
        metrics={
            **metrics,
            "vega_headroom": vega_headroom,
            "vega_size_fraction_allowed": fraction_capped,
        },
    )
