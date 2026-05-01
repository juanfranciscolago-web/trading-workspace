"""
GET /system/status — overview of subsystem health (API/Bus/ATLAS/DB).
GET /system/mode   — current trading mode (paper/real) and uptime.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from multi_agent.api.schemas.system import (
    SystemModeResponse,
    SystemStatusResponse,
)
from multi_agent.config import settings
from multi_agent.system.health_checks import (
    check_atlas,
    check_bus,
    check_db,
)

router = APIRouter(prefix="/system", tags=["system"])


@router.get(
    "/status",
    response_model=SystemStatusResponse,
    summary="System health overview",
)
def status_view(request: Request) -> SystemStatusResponse:
    """
    Returns health of all subsystems. Always responds 200 — individual
    subsystems may report 'error' but the endpoint itself does not fail.
    """
    pool = request.app.state.pool
    buckets = request.app.state.buckets
    limits = request.app.state.limits

    bus_status, bus_ms = check_bus()
    atlas_status, atlas_ms = check_atlas(buckets, limits)
    db_status, db_ms = check_db(pool)

    return SystemStatusResponse(
        api="ok",
        bus=bus_status,
        atlas=atlas_status,
        db=db_status,
        checks_duration_ms={
            "bus": int(bus_ms),
            "atlas": int(atlas_ms),
            "db": int(db_ms),
        },
        checked_at=datetime.now(timezone.utc),
    )


@router.get(
    "/mode",
    response_model=SystemModeResponse,
    summary="Trading mode and uptime",
)
def mode_view(request: Request) -> SystemModeResponse:
    """Returns current trading mode (paper/real) and backend startup time."""
    return SystemModeResponse(
        mode=settings.TRADING_MODE.value,
        since=request.app.state.startup_time,
    )
