"""
Atlas event publishers — emit AlertEvents from ATLAS risk logic.

Each function creates the appropriate AlertEvent and publishes it via AlertBus.
Call these from AtlasConsumer._handle_message() after atlas_validate().
Publish failures are silently swallowed (logged) so the trade cycle is unaffected.
"""
from __future__ import annotations

import logging
from uuid import UUID

from multi_agent.alerts.bus import AlertBus
from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity

logger = logging.getLogger(__name__)
_bus = AlertBus()


def publish_margin_breach(
    ticker: str,
    exposure_pct: float,
    limit_pct: float,
    correlation_id: UUID | None = None,
) -> None:
    """Emitted when a position's exposure exceeds the single-name limit."""
    _bus.publish(AlertEvent(
        event_type=AlertEventType.MARGIN_BREACH,
        severity=AlertSeverity.CRITICAL,
        title=f"Margin breach: {ticker} at {exposure_pct:.1f}% (limit {limit_pct:.1f}%)",
        payload={
            "symbol": ticker,
            "exposure_pct": round(exposure_pct, 4),
            "limit_pct": round(limit_pct, 4),
        },
        source="atlas",
        correlation_id=correlation_id,
    ))
    logger.info("publish_margin_breach ticker=%s exposure=%.2f%%", ticker, exposure_pct)


def publish_stop_loss_hit(
    position_id: str,
    ticker: str,
    pnl_pct: float,
    correlation_id: UUID | None = None,
) -> None:
    """Emitted when a position's PnL crosses the stop-loss threshold."""
    _bus.publish(AlertEvent(
        event_type=AlertEventType.STOP_LOSS_HIT,
        severity=AlertSeverity.CRITICAL,
        title=f"Stop loss hit: {ticker} PnL {pnl_pct:.1f}%",
        payload={
            "position_id": position_id,
            "ticker": ticker,
            "pnl_pct": round(pnl_pct, 4),
        },
        source="atlas",
        correlation_id=correlation_id,
    ))
    logger.info("publish_stop_loss_hit ticker=%s pnl=%.2f%%", ticker, pnl_pct)


def publish_system_failure(
    component: str,
    error_msg: str,
    correlation_id: UUID | None = None,
) -> None:
    """Emitted on unrecoverable errors in a system component."""
    _bus.publish(AlertEvent(
        event_type=AlertEventType.SYSTEM_FAILURE,
        severity=AlertSeverity.CRITICAL,
        title=f"System failure: {component}",
        payload={
            "component": component,
            "error_msg": error_msg[:500],
        },
        source="atlas",
        correlation_id=correlation_id,
    ))
    logger.error("publish_system_failure component=%s", component)


def publish_roll_opportunity(
    position_id: str,
    ticker: str,
    expiry_date: str,
    dte: int,
    current_iv: float,
    correlation_id: UUID | None = None,
) -> None:
    """Emitted when a short option position is approaching expiry and roll is suggested."""
    _bus.publish(AlertEvent(
        event_type=AlertEventType.ROLL_OPPORTUNITY,
        severity=AlertSeverity.WARN,
        title=f"Roll opportunity: {ticker} expiring {expiry_date} ({dte} DTE)",
        payload={
            "position_id": position_id,
            "ticker": ticker,
            "expiry_date": expiry_date,
            "dte": dte,
            "current_iv": round(current_iv, 2),
        },
        source="atlas",
        correlation_id=correlation_id,
    ))
    logger.info("publish_roll_opportunity ticker=%s expiry=%s dte=%d", ticker, expiry_date, dte)
