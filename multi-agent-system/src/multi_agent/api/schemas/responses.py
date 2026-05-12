"""
Response schemas for portfolio, trades, and cost endpoints.

TECH DEBT: CostByAgentResponse, CostByTaskResponse use list[dict]
(untyped). Convert to list[AgentCostRow], list[TaskCostRow] when
ATHENA real generates consistent data with known field shapes.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from multi_agent.communication.schemas import (
    AtlasValidationMessage,
    CritiqueMessage,
    DecisionMessage,
    ProposalMessage,
)


RiskModeOut = Literal["GREEN", "YELLOW", "RED", "BLACK"]


# ── Portfolio ──────────────────────────────────────────────────────────────────

class PositionResponse(BaseModel):
    ticker: str
    asset_class: str
    strategy_type: str | None
    market_value_usd: float
    quantity: int
    delta: float
    vega: float
    theta: float


class SnapshotResponse(BaseModel):
    nav_usd: float
    cash_usd: float
    buying_power_used_pct: float
    portfolio_beta: float
    vega_total: float
    pnl_daily_usd: float
    pnl_daily_pct: float
    pnl_weekly_pct: float
    pnl_monthly_pct: float
    drawdown_from_peak_pct: float
    snapshot_at: str
    snapshot_id: str
    position_count: int


# ── Trades / Validations ───────────────────────────────────────────────────────

class ValidationSummaryItem(BaseModel):
    correlation_id: str
    approved: bool | None
    executed_size_pct: float | None
    original_size_pct: float | None
    reason: str | None
    atlas_version: str | None
    portfolio_snapshot_id: str | None
    evaluation_time_ms: float | None
    checks_passed: list[str] | None
    checks_failed: list[str] | None
    risk_mode: RiskModeOut | None
    created_at: str | None


class ValidationDetailResponse(ValidationSummaryItem):
    metrics_snapshot: dict[str, Any] | None


class ValidationsListResponse(BaseModel):
    items: list[ValidationSummaryItem]
    count: int


# ── Trades / Proposals ─────────────────────────────────────────────────────────

class ProposalSummaryItem(BaseModel):
    correlation_id: str
    proposing_agent: str
    ticker: str
    asset_class: str
    strategy_type: str
    conviction_score: int | None
    proposed_size_pct: float | None
    proposed_size_usd: float | None
    time_horizon_days: int | None
    status: str
    created_at: str


class ProposalsListResponse(BaseModel):
    items: list[ProposalSummaryItem]
    count: int


# ── Costs ──────────────────────────────────────────────────────────────────────

class CostSummaryResponse(BaseModel):
    period_days: int
    total_calls: int
    total_cost_usd: float
    total_tokens: int
    by_model: list[dict[str, Any]]


class CostByAgentResponse(BaseModel):
    # TECH DEBT: untyped list[dict]. Convert to list[AgentCostRow] when
    # ATHENA real generates consistent data with known field shapes.
    period_days: int
    rows: list[dict[str, Any]]


class CostByTaskResponse(BaseModel):
    # TECH DEBT: untyped list[dict]. Convert to list[TaskCostRow] when
    # ATHENA real generates consistent data with known field shapes.
    period_days: int
    rows: list[dict[str, Any]]


class DailyTotalsRow(BaseModel):
    """Single day totals row for /costs/daily endpoint."""
    date: str = Field(description="ISO date (YYYY-MM-DD).")
    calls: int = Field(description="Number of LLM calls on this date.")
    cost_usd: float = Field(description="Total cost in USD.")
    total_tokens: int = Field(description="Total tokens (input + output + cache).")


class CostDailyResponse(BaseModel):
    period_days: int
    rows: list[DailyTotalsRow]


# ── Agents ─────────────────────────────────────────────────────────────────────

class AgentItem(BaseModel):
    """Agent config + state combined for /agents endpoint."""

    # config
    agent_id: str
    display_name: str
    role: str
    time_horizon_min_days: int | None = None
    time_horizon_max_days: int | None = None
    default_llm_model: str
    max_portfolio_pct: Decimal
    is_active: bool

    # state (LEFT JOIN, may be null if agent never started)
    status: str | None = None
    current_task: str | None = None
    last_heartbeat: datetime | None = None
    last_proposal_at: datetime | None = None
    last_error: str | None = None
    error_count_24h: int | None = None
    llm_cost_today_usd: Decimal | None = None


class AgentsListResponse(BaseModel):
    items: list[AgentItem]


# ── Trades / Critiques (Sprint 4 B.4.6) ────────────────────────────────────────

class CritiquesListResponse(BaseModel):
    """List of critiques for a single correlation_id, ordered chronologically.

    Unlike ProposalsListResponse (which uses ProposalSummaryItem to flatten
    the row for table display), this list returns full CritiqueMessage
    instances because the detail page consuming it shows the full critique
    (stance, evidence, concern, etc.) — there is no "summary" rendering."""
    items: list[CritiqueMessage]
    count: int


# ── Trades / Pipeline aggregator (Sprint 4 B.4.6) ──────────────────────────────

class PipelineStatusResponse(BaseModel):
    """Aggregated pipeline state for a correlation_id. The frontend detail
    page polls this endpoint at ~3s intervals while the chain runs async;
    a single round-trip avoids 4 parallel requests per poll.

    Field semantics during the async chain:
    - proposal is always present (the endpoint returns 404 if the
      correlation_id is unknown — there is no 'proposal not yet' state,
      the trigger endpoint persists synchronously before returning).
    - critiques may be empty in the brief window between
      trigger-publish and ApolloConsumer-handle (typically < 1s, but the
      list shape is future-proof for multiple critics in Sprint 5+).
    - decision is None until ConsensusConsumer processes the critique(s).
    - atlas_validation is None until AtlasConsumer processes the decision.
    - status reflects trades.proposals.status: pending → under_critique
      → decided → atlas_validated | rejected (the last two are terminal).
    """
    correlation_id: UUID
    status: str
    proposal: ProposalMessage
    critiques: list[CritiqueMessage]
    decision: DecisionMessage | None
    atlas_validation: AtlasValidationMessage | None
