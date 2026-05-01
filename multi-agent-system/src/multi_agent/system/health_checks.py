"""
Health checks for system subsystems.

Each check returns a tuple (status, duration_ms) and never raises —
so /system/status can always respond 200 with a complete report,
even if some subsystems are down.

Timeouts are 3s to avoid blocking the endpoint on slow infra.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from shared_core.storage.postgres_pool import PostgresPool

from multi_agent.config import settings

logger = logging.getLogger(__name__)

HealthStatus = Literal["ok", "error", "unknown"]
_PING_TIMEOUT_SEC = 3.0


def check_db(pool: "PostgresPool") -> tuple[HealthStatus, float]:
    """
    Ping DB. Returns (status, duration_ms).

    Uses a direct psycopg.connect() with explicit timeout instead of the
    pool, because the PostgresPool wrapper doesn't propagate timeout to
    the underlying psycopg_pool (which defaults to 30s — too long for
    a health check that should fail fast).

    The `pool` arg is kept in the signature for API stability and
    potential future use, but not used for this check.
    """
    import psycopg

    start = time.monotonic()
    try:
        with psycopg.connect(
            settings.DATABASE_URL,
            connect_timeout=int(_PING_TIMEOUT_SEC),
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return "ok", (time.monotonic() - start) * 1000
    except Exception:
        logger.exception("Health check DB failed")
        return "error", (time.monotonic() - start) * 1000


def check_bus() -> tuple[HealthStatus, float]:
    """Ping Redis. Both alerts pub/sub and message_bus streams use same Redis."""
    start = time.monotonic()
    try:
        import redis as _redis
        client = _redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=_PING_TIMEOUT_SEC,
            socket_timeout=_PING_TIMEOUT_SEC,
        )
        client.ping()
        return "ok", (time.monotonic() - start) * 1000
    except Exception:
        logger.exception("Health check Bus (Redis) failed")
        return "error", (time.monotonic() - start) * 1000


def check_atlas(buckets, limits) -> tuple[HealthStatus, float]:
    """
    Verify ATLAS config is loaded. 'ok' if buckets and limits are present.
    Receives them from app.state via dependency injection.
    """
    start = time.monotonic()
    try:
        if buckets is None or limits is None:
            return "error", (time.monotonic() - start) * 1000
        if not buckets or not hasattr(limits, "pnl"):
            return "error", (time.monotonic() - start) * 1000
        return "ok", (time.monotonic() - start) * 1000
    except Exception:
        logger.exception("Health check ATLAS failed")
        return "error", (time.monotonic() - start) * 1000
