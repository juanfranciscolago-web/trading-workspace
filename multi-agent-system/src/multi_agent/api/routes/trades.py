"""
Trades routes.

GET /trades/validations                   — list recent ATLAS validations
GET /trades/validations/{correlation_id} — single validation detail (404 if not found)
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from multi_agent.communication.schemas import ProposalMessage
from multi_agent.persistence.message_repository import MessageRepository
from multi_agent.persistence.validation_repository import ValidationRepository
from multi_agent.api.dependencies import get_message_repo, get_validation_repo
from multi_agent.api.schemas.responses import (
    ProposalSummaryItem,
    ProposalsListResponse,
    ValidationDetailResponse,
    ValidationSummaryItem,
    ValidationsListResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trades", tags=["trades"])


def _row_to_summary(row: dict) -> ValidationSummaryItem:
    return ValidationSummaryItem(
        correlation_id=str(row["correlation_id"]),
        approved=row.get("approved"),
        executed_size_pct=(
            float(row["executed_size_pct"])
            if row.get("executed_size_pct") is not None else None
        ),
        original_size_pct=(
            float(row["original_size_pct"])
            if row.get("original_size_pct") is not None else None
        ),
        reason=row.get("reason"),
        atlas_version=row.get("atlas_version"),
        portfolio_snapshot_id=row.get("portfolio_snapshot_id"),
        evaluation_time_ms=(
            float(row["evaluation_time_ms"])
            if row.get("evaluation_time_ms") is not None else None
        ),
        checks_passed=(
            list(row["checks_passed"])
            if row.get("checks_passed") is not None else None
        ),
        checks_failed=(
            list(row["checks_failed"])
            if row.get("checks_failed") is not None else None
        ),
        risk_mode=row.get("risk_mode"),
        created_at=(
            row["created_at"].isoformat()
            if row.get("created_at") is not None else None
        ),
    )


def _row_to_detail(row: dict) -> ValidationDetailResponse:
    return ValidationDetailResponse(
        **_row_to_summary(row).model_dump(),
        metrics_snapshot=row.get("metrics_snapshot"),
    )


def _row_to_proposal_summary(row: dict) -> ProposalSummaryItem:
    return ProposalSummaryItem(
        correlation_id=str(row["correlation_id"]),
        proposing_agent=row["proposing_agent"],
        ticker=row["ticker"],
        asset_class=row["asset_class"],
        strategy_type=row["strategy_type"],
        conviction_score=row.get("conviction_score"),
        proposed_size_pct=(
            float(row["proposed_size_pct"])
            if row.get("proposed_size_pct") is not None else None
        ),
        proposed_size_usd=(
            float(row["proposed_size_usd"])
            if row.get("proposed_size_usd") is not None else None
        ),
        time_horizon_days=row.get("time_horizon_days"),
        status=row["status"],
        created_at=row["created_at"].isoformat(),
    )


@router.get("/validations", response_model=ValidationsListResponse)
def list_validations(
    approved: Optional[bool] = Query(default=None),
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
    repo: ValidationRepository = Depends(get_validation_repo),
) -> ValidationsListResponse:
    """Recent ATLAS validations. Filter by approved status, lookback window, and limit."""
    rows = repo.list_validations(approved=approved, days=days, limit=limit)
    items = [_row_to_summary(r) for r in rows]
    return ValidationsListResponse(items=items, count=len(items))


@router.get("/validations/{correlation_id}", response_model=ValidationDetailResponse)
def get_validation(
    correlation_id: str,
    repo: ValidationRepository = Depends(get_validation_repo),
) -> ValidationDetailResponse:
    """Single validation detail by correlation_id. Returns 404 if not found."""
    try:
        UUID(correlation_id)
    except ValueError:
        # Invalid UUID format → 404, not 422. From the client's perspective
        # a malformed ID is indistinguishable from "resource doesn't exist".
        raise HTTPException(status_code=404, detail="validation not found")
    row = repo.get_by_correlation_id(correlation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="validation not found")
    return _row_to_detail(row)


@router.get("/proposals", response_model=ProposalsListResponse)
def list_proposals(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
    agent_id: str | None = Query(default=None),
    repo: MessageRepository = Depends(get_message_repo),
) -> ProposalsListResponse:
    """Recent proposals from trades.proposals. Filter by agent_id, lookback window, and limit."""
    rows = repo.list_proposals(days=days, limit=limit, agent_id=agent_id)
    items = [_row_to_proposal_summary(r) for r in rows]
    return ProposalsListResponse(items=items, count=len(items))


@router.get("/proposals/{correlation_id}", response_model=ProposalMessage)
def get_proposal(
    correlation_id: str,
    repo: MessageRepository = Depends(get_message_repo),
) -> ProposalMessage:
    """Single proposal detail by correlation_id. Returns full ProposalMessage. 404 if not found."""
    try:
        UUID(correlation_id)
    except ValueError:
        # Invalid UUID format → 404, not 422. Mirror validations pattern:
        # malformed ID is indistinguishable from "resource doesn't exist".
        raise HTTPException(status_code=404, detail="proposal not found")
    row = repo.get_proposal_by_correlation_id(correlation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    return ProposalMessage.model_validate(row["full_payload"])
