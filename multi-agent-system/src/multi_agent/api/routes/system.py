"""
GET  /system/status — overview of subsystem health (API/Bus/ATLAS/DB).
GET  /system/mode   — current trading mode (paper/real) and time of last change.
POST /system/mode   — toggle trading mode with double-confirmation token (real only).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from multi_agent.alerts.bus import AlertBus
from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity
from multi_agent.api.dependencies import get_system_repo
from multi_agent.api.schemas.system import (
    SystemModeChangeRequest,
    SystemModeResponse,
    SystemStatusResponse,
)
from multi_agent.config import REAL_MODE_TOKEN
from multi_agent.persistence.system_repository import SystemRepository
from multi_agent.system.health_checks import (
    check_atlas,
    check_bus,
    check_db,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/system", tags=["system"])

_bus = AlertBus()


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
    summary="Trading mode and time of last change",
)
def mode_view(request: Request) -> SystemModeResponse:
    """Returns the active trading mode and when it was last changed."""
    state = request.app.state.trading_mode
    return SystemModeResponse(
        mode=state["mode"],
        since=state["since"],
    )


@router.post(
    "/mode",
    response_model=SystemModeResponse,
    summary="Toggle trading mode (idempotent if mode unchanged)",
)
def mode_toggle(
    request: Request,
    body: SystemModeChangeRequest,
    repo: SystemRepository = Depends(get_system_repo),
) -> SystemModeResponse:
    """
    Toggle the active trading mode.

    Idempotent: if body.mode equals the current mode, no DB write is
    performed and no alert is emitted — returns the current state.

    Going to 'real' requires confirmation_token == REAL_MODE_TOKEN.
    Going back to 'paper' is free (no token required).
    """
    state = request.app.state.trading_mode
    current_mode = state["mode"]
    new_mode = body.mode

    if new_mode == current_mode:
        return SystemModeResponse(mode=current_mode, since=state["since"])

    if new_mode == "real" and body.confirmation_token != REAL_MODE_TOKEN:
        raise HTTPException(
            status_code=403,
            detail="confirmation_token required and must equal REAL_MODE_TOKEN to go REAL.",
        )

    inserted = repo.insert_mode_change(
        mode=new_mode,
        source="api",
        confirmation_token=body.confirmation_token if new_mode == "real" else None,
        actor=None,
    )
    request.app.state.trading_mode = {
        "mode": inserted["mode"],
        "since": inserted["changed_at"],
        "source": inserted["source"],
    }

    severity = AlertSeverity.CRITICAL if new_mode == "real" else AlertSeverity.WARN
    event = AlertEvent(
        event_type=AlertEventType.MODE_CHANGED,
        severity=severity,
        title=f"Trading mode changed to {new_mode.upper()}",
        payload={"from": current_mode, "to": new_mode, "source": "api"},
        source="api",
    )
    subscribers = _bus.publish(event)
    logger.info(
        "mode_toggle from=%s to=%s subscribers=%d",
        current_mode, new_mode, subscribers,
    )

    return SystemModeResponse(mode=inserted["mode"], since=inserted["changed_at"])
