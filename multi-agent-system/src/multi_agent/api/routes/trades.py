"""
Trades routes.

GET /trades/validations                   — list recent ATLAS validations
GET /trades/validations/{correlation_id} — single validation detail (404 if not found)
GET /trades/critiques/{correlation_id}   — list critiques for a correlation_id
GET /trades/decisions/{correlation_id}   — single decision detail (404 if not found)
GET /trades/pipeline/{correlation_id}    — aggregated pipeline state (proposal + critiques + decision + atlas_validation)
"""
from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from multi_agent.communication.schemas import DecisionMessage, ProposalMessage
from multi_agent.persistence.message_repository import MessageRepository
from multi_agent.persistence.validation_repository import ValidationRepository
from multi_agent.api.dependencies import get_message_repo, get_validation_repo
from multi_agent.api.schemas.responses import (
    CritiquesListResponse,
    PipelineStatusResponse,
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


@router.get("/critiques/{correlation_id}", response_model=CritiquesListResponse)
def list_critiques(
    correlation_id: str,
    repo: MessageRepository = Depends(get_message_repo),
) -> CritiquesListResponse:
    """List all critiques for a correlation_id, ordered chronologically.

    Returns 200 with empty list if no critiques exist yet (chain
    mid-flight or unknown correlation_id). Does NOT validate that the
    parent proposal exists — list endpoints typically do not check
    parent existence; use GET /trades/pipeline/{cid} for that.
    Malformed UUID → 404 (mirror get_proposal pattern).
    """
    try:
        UUID(correlation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="invalid correlation_id")
    critiques = repo.list_critiques_by_correlation_id(correlation_id)
    return CritiquesListResponse(items=critiques, count=len(critiques))


@router.get("/decisions/{correlation_id}", response_model=DecisionMessage)
def get_decision(
    correlation_id: str,
    repo: MessageRepository = Depends(get_message_repo),
) -> DecisionMessage:
    """Single decision detail by correlation_id. Returns full
    DecisionMessage. 404 if no decision exists yet (chain mid-flight,
    decision not produced) or the correlation_id is unknown."""
    try:
        UUID(correlation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="decision not found")
    decision = repo.get_decision_by_correlation_id(correlation_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return decision


@router.get("/pipeline/{correlation_id}", response_model=PipelineStatusResponse)
def get_pipeline(
    correlation_id: str,
    repo: MessageRepository = Depends(get_message_repo),
) -> PipelineStatusResponse:
    """Aggregated pipeline state for a correlation_id. The frontend detail
    page polls this endpoint while the chain runs async.

    404 if the proposal does not exist (correlation_id is unknown or the
    proposal was deleted). Otherwise 200 with whatever state has been
    produced so far — critiques may be empty, decision and atlas_validation
    may be None.

    Performance: 4 sequential DB queries (proposal + critiques + decision +
    atlas_validation). At local-Postgres latency (~5-15ms each, ~40ms total)
    this is negligible for ~3s polling intervals.
    """
    try:
        UUID(correlation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="proposal not found")
    row = repo.get_proposal_by_correlation_id(correlation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="proposal not found")
    proposal = ProposalMessage.model_validate(row["full_payload"])
    return PipelineStatusResponse(
        correlation_id=UUID(correlation_id),
        status=row["status"],
        proposal=proposal,
        critiques=repo.list_critiques_by_correlation_id(correlation_id),
        decision=repo.get_decision_by_correlation_id(correlation_id),
        atlas_validation=repo.get_atlas_validation_by_correlation_id(correlation_id),
    )
