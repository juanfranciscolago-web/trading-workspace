"""
Alerts routes.

GET  /alerts           — paginated alert history from DB
POST /alerts/test      — fire a test alert (development only)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity
from multi_agent.alerts.bus import AlertBus
from multi_agent.alerts.repository import AlertRepository
from multi_agent.api.dependencies import get_alert_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])

_bus = AlertBus()


@router.get("")
def list_alerts(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    severity: Optional[str] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
    repo: AlertRepository = Depends(get_alert_repo),
) -> dict:
    """Paginated alert history. Filter by severity and/or event_type."""
    rows = repo.list_alerts(
        limit=limit, offset=offset, severity=severity, event_type=event_type
    )
    items = []
    for r in rows:
        item = dict(r)
        for k in ("sent_at", "failed_at", "created_at", "last_retry_at"):
            if item.get(k) is not None:
                item[k] = item[k].isoformat()
        if item.get("correlation_id") is not None:
            item["correlation_id"] = str(item["correlation_id"])
        items.append(item)
    return {"items": items, "count": len(items)}


@router.post("/test", status_code=202)
def fire_test_alert(
    event_type: str = Query(default="system.failure"),
) -> dict:
    """
    Publish a test alert to the alert pipeline.
    Only available when ENVIRONMENT=development.
    Returns 404 in any other environment.
    """
    if os.environ.get("ENVIRONMENT", "development") != "development":
        raise HTTPException(status_code=404, detail="not found")

    try:
        etype = AlertEventType(event_type)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown event_type. Valid: {[e.value for e in AlertEventType]}",
        )

    _SEVERITY = {
        AlertEventType.MARGIN_BREACH: AlertSeverity.CRITICAL,
        AlertEventType.STOP_LOSS_HIT: AlertSeverity.CRITICAL,
        AlertEventType.SYSTEM_FAILURE: AlertSeverity.CRITICAL,
        AlertEventType.ROLL_OPPORTUNITY: AlertSeverity.INFO,
    }
    _PAYLOAD = {
        AlertEventType.MARGIN_BREACH: {"symbol": "TEST", "exposure_pct": 15.0, "limit_pct": 10.0},
        AlertEventType.STOP_LOSS_HIT: {"position_id": "test-pos-1", "ticker": "TEST", "pnl_pct": -9.5},
        AlertEventType.SYSTEM_FAILURE: {"component": "test_component", "error_msg": "This is a test alert"},
        AlertEventType.ROLL_OPPORTUNITY: {"position_id": "test-pos-2", "ticker": "TEST", "expiry_date": "2026-05-16", "dte": 17, "current_iv": 35.0},
    }

    event = AlertEvent(
        event_type=etype,
        severity=_SEVERITY[etype],
        title=f"[TEST] {etype.value}",
        payload=_PAYLOAD[etype],
        source="api_test",
    )
    subscribers = _bus.publish(event)
    logger.info("Test alert fired event_type=%s subscribers=%d", etype.value, subscribers)
    return {
        "published": True,
        "event_type": etype.value,
        "subscribers": subscribers,
    }
