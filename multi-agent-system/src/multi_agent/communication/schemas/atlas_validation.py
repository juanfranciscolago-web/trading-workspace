from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..base import BaseMessage
from ..enums import AtlasDecision, MessageType, RiskMode


class PortfolioState(BaseModel):
    portfolio_beta: float
    tech_concentration_pct: float
    vega_total: float
    drawdown_from_peak_pct: float
    buying_power_used_pct: float


class LimitDistances(BaseModel):
    tech_concentration_limit: float
    distance_to_limit_pct: float
    vega_limit: float
    distance_to_vega_limit_pct: float


class PortfolioImpact(BaseModel):
    current_state: PortfolioState
    post_trade_state: PortfolioState
    limit_distances: LimitDistances


class StressTestResult(BaseModel):
    scenario: str
    projected_pl_usd: float
    projected_pl_pct: float


class AtlasValidationMessage(BaseMessage):
    message_type: Literal[MessageType.ATLAS_VALIDATION] = MessageType.ATLAS_VALIDATION
    decision: AtlasDecision
    portfolio_impact: PortfolioImpact
    stress_test_results: list[StressTestResult] = Field(min_length=1)
    modulations_applied: list[str] = Field(default_factory=list)
    risk_mode: RiskMode
