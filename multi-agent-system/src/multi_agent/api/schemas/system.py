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
    """Current trading mode and backend startup time."""
    mode: TradingModeOut = Field(
        description="paper or real, controlled by TRADING_MODE env var.",
    )
    since: datetime = Field(
        description="When the backend started (UTC).",
    )
