"""
FastAPI application factory for the multi-agent trading API.

SECURITY NOTE: No authentication. Localhost-only (uvicorn binds 127.0.0.1).
Do NOT expose to public internet. Auth planned for Sprint 3+.

Usage:
    uvicorn multi_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
    (or use scripts/run_api.sh)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from multi_agent.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialize shared resources on startup; close on shutdown."""
    import asyncio
    from shared_core.storage.postgres_pool import PostgresPool
    from multi_agent.risk.config import load_buckets, load_limits
    from multi_agent.risk.portfolio_snapshot import CachedSnapshotBuilder, SnapshotBuilder
    from multi_agent.observability.llm_cost_repository import LLMCostRepository
    from multi_agent.alerts.bus import AlertBus
    from multi_agent.alerts.dedup import AlertDedup
    from multi_agent.alerts.repository import AlertRepository
    from multi_agent.alerts.router import AlertRouter
    from multi_agent.alerts.sinks.telegram import TelegramSink
    from multi_agent.alerts.worker import AlertWorker

    # Emit warnings that couldn't be logged at import time (logging not yet configured)
    settings.log_startup_warnings()

    pool = PostgresPool(
        dsn=settings.DATABASE_URL,
        min_connections=settings.DB_POOL_MIN,
        max_connections=settings.DB_POOL_MAX,
    )
    app.state.pool = pool
    app.state.limits = load_limits()
    app.state.buckets = load_buckets()
    app.state.snapshot_builder = CachedSnapshotBuilder(SnapshotBuilder(pool), ttl_seconds=5.0)
    app.state.cost_repo = LLMCostRepository(pool)
    logger.info("✓ DB pool ready (min=%d max=%d)", settings.DB_POOL_MIN, settings.DB_POOL_MAX)

    # Alert pipeline
    alert_bus = AlertBus()
    alert_repo = AlertRepository(pool)
    alert_router = AlertRouter(
        dedup=AlertDedup(),
        sinks=[TelegramSink()],
        repo=alert_repo,
    )
    alert_worker = AlertWorker(bus=alert_bus, router=alert_router)
    worker_task = asyncio.create_task(alert_worker.run())
    app.state.alert_worker = alert_worker
    logger.info("✓ AlertWorker started")

    # Telegram bot — inbound command polling.
    # Pool injected via bot_data so handlers share the same pool as the API
    # (no get_pool() singleton divergence). Fail-isolated: errors here must
    # not block startup since alert delivery (TelegramSink) is a separate path.
    tg_app = None
    try:
        from multi_agent.telegram_bot.bot import build_application
        tg_app = build_application()
        tg_app.bot_data["pool"] = pool       # inject shared pool
        await tg_app.initialize()
        await tg_app.start()
        await tg_app.updater.start_polling()
        username = getattr(tg_app.bot, "username", None) or "unknown"
        logger.info("✓ TelegramBot polling started for @%s", username)
    except RuntimeError as exc:
        logger.warning("✗ TelegramBot disabled: %s", exc)
        tg_app = None
    except Exception as exc:
        logger.error("✗ TelegramBot failed to start (API continues): %r", exc)
        tg_app = None

    app.state.tg_app = tg_app

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────

    if tg_app is not None:
        try:
            await tg_app.updater.stop()
            await tg_app.stop()
            await tg_app.shutdown()
            logger.info("TelegramBot stopped cleanly")
        except Exception:
            logger.exception("TelegramBot shutdown error (continuing)")

    alert_worker.shutdown()
    try:
        await asyncio.wait_for(worker_task, timeout=10.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.warning("Alert worker did not stop cleanly within 10s")

    pool.close_all()
    logger.info("API shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi-Agent Trading API",
        version="0.1.0",
        description="Internal API for ATLAS risk validation and observability.",
        lifespan=_lifespan,
    )

    from multi_agent.api.routes.alerts import router as alerts_router
    from multi_agent.api.routes.atlas import router as atlas_router
    from multi_agent.api.routes.portfolio import router as portfolio_router
    from multi_agent.api.routes.trades import router as trades_router
    from multi_agent.api.routes.costs import router as costs_router
    app.include_router(alerts_router)
    app.include_router(atlas_router)
    app.include_router(portfolio_router)
    app.include_router(trades_router)
    app.include_router(costs_router)

    return app
