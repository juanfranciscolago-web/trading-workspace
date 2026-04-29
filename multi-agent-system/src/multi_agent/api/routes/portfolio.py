"""
Portfolio routes.

GET /portfolio/snapshot   — current cached portfolio snapshot summary
GET /portfolio/positions  — individual positions from the current snapshot
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from multi_agent.risk.portfolio_snapshot import CachedSnapshotBuilder
from multi_agent.api.dependencies import get_snapshot_builder
from multi_agent.api.schemas.responses import PositionResponse, SnapshotResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _pos_to_response(pos) -> PositionResponse:
    return PositionResponse(
        ticker=pos.ticker,
        asset_class=pos.asset_class,
        strategy_type=pos.strategy_type,
        market_value_usd=float(pos.market_value_usd),
        quantity=pos.quantity,
        delta=float(pos.delta),
        vega=float(pos.vega),
        theta=float(pos.theta),
    )


@router.get("/snapshot", response_model=SnapshotResponse)
def snapshot(
    snapshot_builder: CachedSnapshotBuilder = Depends(get_snapshot_builder),
) -> SnapshotResponse:
    """Current portfolio snapshot (cached, TTL 5s)."""
    s = snapshot_builder.get()
    return SnapshotResponse(
        nav_usd=float(s.nav_usd),
        cash_usd=float(s.cash_usd),
        buying_power_used_pct=s.buying_power_used_pct,
        portfolio_beta=s.portfolio_beta,
        vega_total=s.vega_total,
        pnl_daily_usd=float(s.pnl_daily_usd),
        pnl_daily_pct=s.pnl_daily_pct,
        pnl_weekly_pct=s.pnl_weekly_pct,
        pnl_monthly_pct=s.pnl_monthly_pct,
        drawdown_from_peak_pct=s.drawdown_from_peak_pct,
        snapshot_at=s.snapshot_at.isoformat(),
        snapshot_id=s.snapshot_id,
        position_count=len(s.positions),
    )


@router.get("/positions", response_model=list[PositionResponse])
def positions(
    snapshot_builder: CachedSnapshotBuilder = Depends(get_snapshot_builder),
) -> list[PositionResponse]:
    """All positions from the current cached snapshot."""
    s = snapshot_builder.get()
    return [_pos_to_response(p) for p in s.positions]
