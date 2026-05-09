from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from shared_core.models import AssetClass
from multi_agent.communication.enums import StrategyType


RiskModeOut = Literal["GREEN", "YELLOW", "RED", "BLACK"]


class ValidateRequest(BaseModel):
    """Input for POST /atlas/validate.

    asset_class defaults to OPTION (activates all checks including vega).
    Override to EQUITY/CRYPTO for non-option strategies to skip vega check.
    """
    ticker: str = Field(..., min_length=1, max_length=32)
    strategy_type: StrategyType
    asset_class: AssetClass = AssetClass.OPTION
    proposed_size_pct: float = Field(..., gt=0, le=100, description="% of portfolio NAV")
    buying_power_required: float = Field(..., gt=0, description="USD buying power required")
    conviction_score: int = Field(..., ge=0, le=100)


class ValidateResponse(BaseModel):
    """Output for POST /atlas/validate. Always 200 — approved=False means ATLAS blocked."""
    correlation_id: str
    approved: bool
    executed_size_pct: float
    original_size_pct: float
    reason: str
    risk_mode: RiskModeOut
    checks_passed: list[str]
    checks_failed: list[str]
    evaluation_time_ms: float
    atlas_version: str
    portfolio_snapshot_id: str
    metrics_snapshot: dict


class HealthResponse(BaseModel):
    status: str
    risk_mode: RiskModeOut
    nav_usd: float
    snapshot_id: str
    ts: str  # ISO-8601


# ── Limits / Buckets ──────────────────────────────────────────────────────────

class PnlLimitsOut(BaseModel):
    daily_halt_pct: float
    weekly_halt_pct: float
    monthly_size_reduction_pct: float
    drawdown_halt_pct: float
    drawdown_kill_switch_pct: float
    daily_loss_kill_switch_pct: float


class ExposureLimitsOut(BaseModel):
    single_name_max_pct: float
    sector_max_pct: float
    bucket_max_pct: float
    beta_min: float
    beta_max: float


class GreekLimitsOut(BaseModel):
    vega_limit_pct_per_vix_point: float


class BuyingPowerLimitsOut(BaseModel):
    normal_max_pct: float
    macro_event_max_pct: float


class LimitsResponse(BaseModel):
    phase: int
    pnl: PnlLimitsOut
    exposure: ExposureLimitsOut
    greeks: GreekLimitsOut
    buying_power: BuyingPowerLimitsOut


class BucketDetail(BaseModel):
    description: str
    tickers: list[str]


class BucketsResponse(BaseModel):
    buckets: dict[str, BucketDetail]
