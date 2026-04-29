"""
ATLAS API routes.

GET  /atlas/health    — risk mode + portfolio summary (async, reads snapshot)
POST /atlas/validate  — run ATLAS checks on a proposed trade (returns 200 always)
GET  /atlas/limits    — current Phase1Limits config (cached, from YAML)
GET  /atlas/buckets   — ticker→bucket mapping (cached, from YAML)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends

from shared_core.models import AssetClass, Direction, OptionType
from multi_agent.communication.enums import (
    AgentId, ConsensusType, DecisionOutcome, StrategyType,
)
from multi_agent.communication.schemas import ProposalMessage, DecisionMessage
from multi_agent.communication.schemas.decision import ConsensusState
from multi_agent.communication.schemas.proposal import (
    DataSignature, OptionLeg, Thesis, TradeDetails, TradeSizing, TradeStructure,
)
from multi_agent.risk import atlas_validate, get_current_risk_mode
from multi_agent.risk.config import BucketConfig, Phase1Limits
from multi_agent.risk.portfolio_snapshot import CachedSnapshotBuilder

from multi_agent.api.dependencies import get_buckets, get_limits, get_snapshot_builder
from multi_agent.api.schemas.atlas import (
    BucketDetail, BucketsResponse, HealthResponse,
    LimitsResponse, ValidateRequest, ValidateResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/atlas", tags=["atlas"])


# ── GET /atlas/health ─────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health(
    snapshot_builder: CachedSnapshotBuilder = Depends(get_snapshot_builder),
    limits: Phase1Limits = Depends(get_limits),
) -> HealthResponse:
    """Current risk mode and portfolio summary. Uses cached snapshot (TTL 5s)."""
    snapshot = snapshot_builder.get()
    risk_mode = get_current_risk_mode(snapshot, limits)
    return HealthResponse(
        status="ok",
        risk_mode=risk_mode.value,
        nav_usd=float(snapshot.nav_usd),
        snapshot_id=snapshot.snapshot_id,
        ts=snapshot.snapshot_at.isoformat(),
    )


# ── POST /atlas/validate ──────────────────────────────────────────────────────

@router.post("/validate", response_model=ValidateResponse)
def validate(
    req: ValidateRequest,
    snapshot_builder: CachedSnapshotBuilder = Depends(get_snapshot_builder),
    limits: Phase1Limits = Depends(get_limits),
    buckets: BucketConfig = Depends(get_buckets),
) -> ValidateResponse:
    """
    Run ATLAS risk checks on a proposed trade.

    Always returns HTTP 200. approved=False means ATLAS blocked the trade —
    this is a valid response, not an error. HTTP 422 signals invalid input only.

    Builds synthetic ProposalMessage and DecisionMessage internally.
    asset_class=OPTION (default) activates all checks including vega.
    Override to EQUITY/CRYPTO to skip vega for non-option strategies.
    """
    snapshot = snapshot_builder.get()
    proposal = _build_proposal(req)
    decision = _build_decision(proposal)

    result = atlas_validate(proposal, decision, snapshot, limits, buckets)

    return ValidateResponse(
        correlation_id=str(result.correlation_id),
        approved=result.approved,
        executed_size_pct=float(result.executed_size),
        original_size_pct=float(result.original_size),
        reason=result.reason,
        risk_mode=result.risk_mode.value,
        checks_passed=list(result.checks_passed),
        checks_failed=list(result.checks_failed),
        evaluation_time_ms=result.evaluation_time_ms,
        atlas_version=result.atlas_version,
        portfolio_snapshot_id=result.portfolio_snapshot_id,
        metrics_snapshot=result.metrics_snapshot,
    )


# ── GET /atlas/limits ─────────────────────────────────────────────────────────

@router.get("/limits", response_model=LimitsResponse)
def limits_view(limits: Phase1Limits = Depends(get_limits)) -> LimitsResponse:
    """Current Phase 1 risk limits (from config/limits.yaml, lru_cached)."""
    return LimitsResponse(**limits.model_dump())


# ── GET /atlas/buckets ────────────────────────────────────────────────────────

@router.get("/buckets", response_model=BucketsResponse)
def buckets_view(buckets: BucketConfig = Depends(get_buckets)) -> BucketsResponse:
    """Ticker→bucket mapping (from config/buckets.yaml, lru_cached)."""
    return BucketsResponse(
        buckets={
            name: BucketDetail(
                description=bucket.description,
                tickers=list(bucket.tickers),
            )
            for name, bucket in buckets.buckets.items()
        }
    )


# ── Synthetic message builders ────────────────────────────────────────────────

def _build_proposal(req: ValidateRequest) -> ProposalMessage:
    """
    Build a minimal ProposalMessage from the API request.

    Uses a placeholder OptionLeg (ATLAS checks use size_pct and buying_power,
    not individual leg details). asset_class is passed through from the request
    so the vega check is correctly activated only for options strategies.
    """
    return ProposalMessage(
        agent_id=AgentId.ATHENA,
        trade=TradeDetails(
            ticker=req.ticker.upper(),
            asset_class=req.asset_class,
            strategy_type=req.strategy_type,
            structure=TradeStructure(
                legs=[
                    OptionLeg(
                        action=Direction.SELL,
                        instrument_type=OptionType.PUT,
                        strike=Decimal("100"),
                        expiration=date.today() + timedelta(days=30),
                        quantity=1,
                    )
                ],
                buying_power_required=Decimal(str(req.buying_power_required)),
            ),
        ),
        thesis=Thesis(
            premise="API synthetic validation",
            mechanism="api_call",
            key_data_points=["api"],
            invalidation="N/A",
            target="N/A",
            time_horizon_days=30,
            expected_holding_period_days=15,
        ),
        sizing=TradeSizing(
            proposed_size_pct_portfolio=req.proposed_size_pct,
            proposed_size_usd=Decimal(str(round(req.proposed_size_pct * 10_000, 2))),
            kelly_suggested=req.proposed_size_pct,
            kelly_fraction_applied=0.5,
        ),
        data_signature=DataSignature(
            data_sources=["api"],
            data_timestamp=datetime.now(timezone.utc),
            model_version="api-1.0",
        ),
        conviction_score=req.conviction_score,
    )


def _build_decision(proposal: ProposalMessage) -> DecisionMessage:
    return DecisionMessage(
        agent_id=AgentId.ATLAS,
        correlation_id=proposal.correlation_id,
        parent_message_id=proposal.message_id,
        outcome=DecisionOutcome.APPROVED,
        consensus_state=ConsensusState(
            agree=[AgentId.ATHENA],
            consensus_type=ConsensusType.UNANIMOUS,
        ),
    )
