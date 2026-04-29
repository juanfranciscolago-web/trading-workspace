"""
Cost routes.

GET /costs/summary   — aggregate LLM cost stats for a period
GET /costs/by-agent  — costs grouped by agent_id
GET /costs/by-task   — costs grouped by task_type
GET /costs/daily     — daily cost totals
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from multi_agent.observability.llm_cost_repository import LLMCostRepository
from multi_agent.api.dependencies import get_cost_repo
from multi_agent.api.schemas.responses import (
    CostByAgentResponse,
    CostByTaskResponse,
    CostDailyResponse,
    CostSummaryResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("/summary", response_model=CostSummaryResponse)
def cost_summary(
    days: int = Query(default=7, ge=1, le=90),
    cost_repo: LLMCostRepository = Depends(get_cost_repo),
) -> CostSummaryResponse:
    """Aggregate LLM cost stats for the given lookback period."""
    data = cost_repo.get_summary_by_period(days=days)
    return CostSummaryResponse(
        period_days=days,
        total_calls=data.get("total_calls", 0),
        total_cost_usd=float(data.get("total_cost_usd", 0.0)),
        total_tokens=data.get("total_tokens", 0),
        by_model=data.get("by_model", []),
    )


@router.get("/by-agent", response_model=CostByAgentResponse)
def cost_by_agent(
    days: int = Query(default=7, ge=1, le=90),
    cost_repo: LLMCostRepository = Depends(get_cost_repo),
) -> CostByAgentResponse:
    """LLM costs grouped by agent_id for the given lookback period."""
    rows = cost_repo.get_by_agent(days=days)
    return CostByAgentResponse(period_days=days, rows=rows)


@router.get("/by-task", response_model=CostByTaskResponse)
def cost_by_task(
    days: int = Query(default=7, ge=1, le=90),
    cost_repo: LLMCostRepository = Depends(get_cost_repo),
) -> CostByTaskResponse:
    """LLM costs grouped by task_type for the given lookback period."""
    rows = cost_repo.get_by_task(days=days)
    return CostByTaskResponse(period_days=days, rows=rows)


@router.get("/daily", response_model=CostDailyResponse)
def cost_daily(
    days: int = Query(default=7, ge=1, le=90),
    cost_repo: LLMCostRepository = Depends(get_cost_repo),
) -> CostDailyResponse:
    """Daily LLM cost totals for the given lookback period."""
    rows = cost_repo.get_daily_totals(days=days)
    return CostDailyResponse(period_days=days, rows=rows)
