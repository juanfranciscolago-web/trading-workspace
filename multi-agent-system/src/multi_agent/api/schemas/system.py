"""Schemas for /system endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


HealthStatusOut = Literal["ok", "error", "unknown"]
TradingModeOut = Literal["paper", "real"]


class SystemStatusResponse(BaseModel):
    """Health overview of all subsystems."""
    api: HealthStatusOut = Field(
        description="API service. Always 'ok' if this endpoint responded.",
    )
    bus: HealthStatusOut = Field(
        description="Redis bus (used by alerts pub/sub and message streams).",
    )
    atlas: HealthStatusOut = Field(
        description="ATLAS risk module (buckets and limits loaded).",
    )
    db: HealthStatusOut = Field(
        description="PostgreSQL connection pool.",
    )
    checks_duration_ms: dict[str, int] = Field(
        description="Duration of each individual health check in milliseconds.",
    )
    checked_at: datetime = Field(
        description="When the health checks were performed (UTC).",
    )


class SystemModeResponse(BaseModel):
    """Current trading mode and time of last mode change."""
    mode: TradingModeOut = Field(
        description="Active trading mode (initial value from TRADING_MODE env, changeable via POST /system/mode).",
    )
    since: datetime = Field(
        description="When the trading mode was last changed (UTC).",
    )


class SystemModeChangeRequest(BaseModel):
    """Body for POST /system/mode — toggle the active trading mode."""
    mode: TradingModeOut = Field(
        description="The mode to switch to. Idempotent if equal to the current mode.",
    )
    confirmation_token: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Required when mode='real'. Must equal the REAL_MODE_TOKEN constant. "
            "Ignored when mode='paper'."
        ),
    )
