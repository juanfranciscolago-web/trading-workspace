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
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from multi_agent.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialize shared resources on startup; close on shutdown."""
    import asyncio
    from claude_router.router import ClaudeRouter
    from shared_core.storage.postgres_pool import PostgresPool
    from multi_agent.risk.config import load_buckets, load_limits
    from multi_agent.risk.portfolio_snapshot import CachedSnapshotBuilder, SnapshotBuilder
    from multi_agent.observability.llm_cost_repository import LLMCostRepository
    from multi_agent.persistence.system_repository import SystemRepository
    from multi_agent.data_layer import StubDataLayer
    from multi_agent.alerts.bus import AlertBus
    from multi_agent.alerts.dedup import AlertDedup
    from multi_agent.alerts.repository import AlertRepository
    from multi_agent.alerts.retry_worker import RetryWorker
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
    app.state.startup_time = datetime.now(timezone.utc)
    logger.info("✓ DB pool ready (min=%d max=%d)", settings.DB_POOL_MIN, settings.DB_POOL_MAX)

    # DB-backed mode: bootstrap from env on first run, otherwise read latest.
    system_repo = SystemRepository(pool)
    current_mode = system_repo.get_current_mode()
    if current_mode is None:
        current_mode = system_repo.insert_mode_change(
            mode=settings.TRADING_MODE.value,
            source="env",
        )
    app.state.trading_mode = {
        "mode": current_mode["mode"],
        "since": current_mode["changed_at"],
        "source": current_mode["source"],
    }
    logger.info(
        "✓ Trading mode: %s (since %s, source=%s)",
        app.state.trading_mode["mode"],
        app.state.trading_mode["since"].isoformat(),
        app.state.trading_mode["source"],
    )

    # ATHENA real agent dependencies (Sprint 3 B.3.5).
    # Config path: env override + project-root fallback (mirrors risk/config.py).
    default_router_config = (
        Path(__file__).resolve().parents[3]
        / "claude_router" / "config" / "routing_rules.yaml"
    )
    router_config_path = os.environ.get("CLAUDE_ROUTER_CONFIG", str(default_router_config))
    app.state.claude_router = ClaudeRouter.from_config(router_config_path)
    app.state.data_layer = StubDataLayer()
    logger.info(
        "✓ ATHENA dependencies ready: claude_router (config=%s), data_layer=StubDataLayer",
        router_config_path,
    )

    # Agent message bus (Sprint 4 B.4.4) — Redis-backed pub/sub for the
    # trigger → workers chain. decode_responses=False keeps bytes payloads
    # so AgentMessageBus can serialize Pydantic models for XADD.
    import redis
    from multi_agent.communication.message_bus import AgentMessageBus
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=False)
    app.state.redis_client = redis_client
    app.state.message_bus = AgentMessageBus(redis_client)
    logger.info("✓ AgentMessageBus ready (REDIS_URL=%s)", settings.REDIS_URL)

    # Alert pipeline
    alert_bus = AlertBus()
    alert_repo = AlertRepository(pool)
    alert_sink = TelegramSink()  # shared between router and retry worker
    alert_router = AlertRouter(
        dedup=AlertDedup(),
        sinks=[alert_sink],
        repo=alert_repo,
    )
    alert_worker = AlertWorker(bus=alert_bus, router=alert_router)
    worker_task = asyncio.create_task(alert_worker.run())
    app.state.alert_worker = alert_worker

    retry_worker = RetryWorker(
        sink=alert_sink,
        repo=alert_repo,
        interval=settings.ALERT_RETRY_INTERVAL_SECONDS,
    )
    retry_task = asyncio.create_task(retry_worker.run())
    app.state.retry_worker = retry_worker
    logger.info("✓ AlertWorker + RetryWorker started (retry_interval=%ds)",
                settings.ALERT_RETRY_INTERVAL_SECONDS)

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
    retry_worker.shutdown()
    try:
        await asyncio.wait_for(
            asyncio.gather(worker_task, retry_task, return_exceptions=True),
            timeout=10.0,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.warning("Alert workers did not stop cleanly within 10s")

    try:
        app.state.redis_client.close()
        logger.info("Redis client (agent message bus) closed")
    except Exception:
        logger.exception("Redis client shutdown error (continuing)")

    pool.close_all()
    logger.info("API shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi-Agent Trading API",
        version="0.1.0",
        description="Internal API for ATLAS risk validation and observability.",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    from multi_agent.api.routes.alerts import router as alerts_router
    from multi_agent.api.routes.atlas import router as atlas_router
    from multi_agent.api.routes.portfolio import router as portfolio_router
    from multi_agent.api.routes.trades import router as trades_router
    from multi_agent.api.routes.costs import router as costs_router
    from multi_agent.api.routes.system import router as system_router
    from multi_agent.api.routes.agents import router as agents_router
    from multi_agent.api.routes.config import router as config_router
    app.include_router(alerts_router)
    app.include_router(atlas_router)
    app.include_router(portfolio_router)
    app.include_router(trades_router)
    app.include_router(costs_router)
    app.include_router(system_router)
    app.include_router(agents_router)
    app.include_router(config_router)

    return app
