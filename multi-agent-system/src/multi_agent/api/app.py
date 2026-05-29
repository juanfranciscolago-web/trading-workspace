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
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from multi_agent.config import Settings, settings
from multi_agent.data_layer.interfaces import DataLayer

if TYPE_CHECKING:
    from multi_agent.persistence.iv_history_repository import IvHistoryRepository
    from multi_agent.persistence.iv_surface_repository import IvSurfaceRepository
    from multi_agent.persistence.ohlcv_repository import OhlcvRepository

logger = logging.getLogger(__name__)


def _build_schwab_client(settings_obj: Settings):
    """Singleton SchwabClient factory (F-r16 resolution Sprint 14 f-r16-a).

    Returns single SchwabClient instance shared across consumers
    (SchwabDataLayer + LiveSnapshotBuilder + IvHistoryWorker + OhlcvWorker).
    Resolves ADR-013 §9.3 #6 + ADR-005 §9.3 #1 reaffirmed cross-cutting
    tech debt: 4 SchwabClient instances → 1 singleton.

    Conditional lazy creation: returns None if NO consumer needs SchwabClient
    (full synthetic mode + workers disabled — workers conditional on
    USE_SCHWAB_DATA_LAYER per current lifespan logic).

    account_id strategy: settings.SCHWAB_ACCOUNT_ID if USE_LIVE_PORTFOLIO
    else None (auto-discovery for non-portfolio market data uses).
    Fail-fast contract D-ν preserved (per ADR-013 D-ο Sprint 11 atlas-e):
    USE_LIVE_PORTFOLIO=True + SCHWAB_ACCOUNT_ID="" raises ValueError.
    """
    needs_schwab = (
        settings_obj.USE_SCHWAB_DATA_LAYER
        or settings_obj.USE_LIVE_PORTFOLIO
    )
    if not needs_schwab:
        return None

    if settings_obj.USE_LIVE_PORTFOLIO and not settings_obj.SCHWAB_ACCOUNT_ID:
        raise ValueError(
            "USE_LIVE_PORTFOLIO=True requires SCHWAB_ACCOUNT_ID explicit "
            "(ADR-013 D9 subaccount isolation). Auto-discovery would "
            "silently use Eolo's subaccount, causing position conflation. "
            "Set SCHWAB_ACCOUNT_ID env var to your multi-agent paper "
            "subaccount number, or set USE_LIVE_PORTFOLIO=False."
        )

    from shared_core.brokers.schwab_client import SchwabClient

    account_id = (
        settings_obj.SCHWAB_ACCOUNT_ID if settings_obj.USE_LIVE_PORTFOLIO else None
    )
    return SchwabClient.from_gcp(account_id=account_id)


def _build_schwab_streamer(settings_obj: Settings, schwab_client):
    """Singleton SchwabStreamer factory (ADR-010 D4 Sprint 15 ws-a).

    Lazy conditional creation mirror F-r16 SchwabClient pattern.
    Returns None if USE_SCHWAB_WEBSOCKET=False OR schwab_client=None
    (streamer requires shared SchwabClient for auth via access_token).

    Args:
        settings_obj: Settings instance with USE_SCHWAB_WEBSOCKET flag.
        schwab_client: shared SchwabClient instance (per F-r16 singleton).

    Returns:
        SchwabStreamer instance if flag True + client viable; else None.
    """
    if not settings_obj.USE_SCHWAB_WEBSOCKET:
        return None
    if schwab_client is None:
        logger.warning(
            "USE_SCHWAB_WEBSOCKET=True but schwab_client is None — "
            "streamer requires SchwabClient instance for auth. Returning None."
        )
        return None

    from shared_core.brokers.schwab_streamer import SchwabStreamer
    return SchwabStreamer(schwab_client=schwab_client)


def _select_data_layer(
    settings_obj: Settings,
    iv_history_repo: IvHistoryRepository | None = None,
    iv_surface_repo: IvSurfaceRepository | None = None,
    ohlcv_repo: OhlcvRepository | None = None,
    schwab_client=None,
) -> DataLayer:
    """Construct the DataLayer per USE_SCHWAB_DATA_LAYER flag.

    Fail-fast contract (D-mmm): if USE_SCHWAB_DATA_LAYER=True but
    SchwabDataLayer construction fails (GCP creds missing, Firestore tokens
    not bootstrapped, etc.), the function re-raises after logging — the app
    refuses to start. NO silent fallback to StubDataLayer (would mislead
    the operator into believing real data was active).

    Args:
        settings_obj: Settings instance (passed explicitly for testability
            instead of reading the module-level `settings`).
        iv_history_repo: Optional IvHistoryRepository for real iv_rank
            compute (S.6.iv-d). Passed by lifespan when
            USE_SCHWAB_DATA_LAYER=True. None for tests / StubDataLayer path /
            fallback — SchwabDataLayer falls back to iv_rank=50.0 per
            ADR-005 D5 N<10 semantics when None.

    Returns:
        SchwabDataLayer if flag enabled and construction succeeds; otherwise
        StubDataLayer.

    Raises:
        Exception: When USE_SCHWAB_DATA_LAYER=True but SchwabClient.from_gcp()
            or SchwabDataLayer() construction fails. Operator must either
            (a) set USE_SCHWAB_DATA_LAYER=False to fall back to StubDataLayer,
            or (b) fix the underlying GCP / Firestore configuration before
            restarting.
    """
    if settings_obj.USE_SCHWAB_DATA_LAYER:
        from multi_agent.data_layer import SchwabDataLayer
        from shared_core.brokers.schwab_client import SchwabClient

        try:
            # F-r16 (Sprint 14 f-r16-a): use passed singleton if provided;
            # else legacy from_gcp (tests + backward compat preserved).
            if schwab_client is None:
                schwab_client = SchwabClient.from_gcp()
            data_layer = SchwabDataLayer(
                schwab_client,
                iv_history_repo=iv_history_repo,
                iv_surface_repo=iv_surface_repo,
                ohlcv_repo=ohlcv_repo,
            )
            iv_mode = "real (ADR-005 D5)" if iv_history_repo else "50.0 fallback"
            logger.info(
                "✓ SchwabDataLayer active (real broker data, iv_rank=%s)",
                iv_mode,
            )
            return data_layer
        except Exception:
            logger.exception(
                "USE_SCHWAB_DATA_LAYER=True but SchwabDataLayer construction "
                "failed. Refusing to start. Set USE_SCHWAB_DATA_LAYER=False "
                "to fall back to StubDataLayer, or fix the underlying GCP / "
                "Firestore configuration."
            )
            raise
    else:
        from multi_agent.data_layer import StubDataLayer

        data_layer = StubDataLayer()
        logger.info(
            "✓ StubDataLayer active (synthetic data, default for Sprint 5)"
        )
        return data_layer


def _build_snapshot_builder(settings_obj: Settings, pool, schwab_client=None):
    """Construct snapshot builder per USE_LIVE_PORTFOLIO flag (ADR-013 D6 + D7).

    USE_LIVE_PORTFOLIO=False (default) → DB-backed SnapshotBuilder + TTL 5s.
    USE_LIVE_PORTFOLIO=True → LiveSnapshotBuilder via SchwabClient + TTL 30s.

    Fail-fast contract (ADR-013 D-ν STRENGTHENED + D-ο):
    - If USE_LIVE_PORTFOLIO=True but SCHWAB_ACCOUNT_ID="" → ValueError
      (refuse to start). Auto-discovery would silently use Eolo's subaccount,
      causing position conflation. ADR-013 D9 requires explicit subaccount.
    - If USE_LIVE_PORTFOLIO=True and SchwabClient.from_gcp() fails → propagate
      (mirror _select_data_layer pattern).

    Args:
        settings_obj: Settings instance with USE_LIVE_PORTFOLIO + SCHWAB_ACCOUNT_ID.
        pool: PostgresPool for DB-backed SnapshotBuilder fallback path.

    Returns:
        CachedSnapshotBuilder wrapping either LiveSnapshotBuilder (live mode) or
        SnapshotBuilder (synthetic mode).

    Raises:
        ValueError: si USE_LIVE_PORTFOLIO=True pero SCHWAB_ACCOUNT_ID="" (ADR-013 D-ο).
        Exception: GCP/Firestore credentials issues si USE_LIVE_PORTFOLIO=True.
    """
    # Lazy import to avoid top-level circular issues + match _lifespan style.
    from multi_agent.risk.portfolio_snapshot import (
        CachedSnapshotBuilder,
        LiveSnapshotBuilder,
        SnapshotBuilder,
    )

    if settings_obj.USE_LIVE_PORTFOLIO:
        # ADR-013 D-ο fail-fast: explicit account_id REQUIRED.
        if not settings_obj.SCHWAB_ACCOUNT_ID:
            raise ValueError(
                "USE_LIVE_PORTFOLIO=True requires SCHWAB_ACCOUNT_ID explicit "
                "(ADR-013 D9 subaccount isolation). Auto-discovery would "
                "silently use Eolo's subaccount, causing position conflation. "
                "Set SCHWAB_ACCOUNT_ID env var to your multi-agent paper "
                "subaccount number, or set USE_LIVE_PORTFOLIO=False to use "
                "DB-backed SnapshotBuilder."
            )

        from shared_core.brokers.schwab_client import SchwabClient

        try:
            # F-r16 (Sprint 14 f-r16-a): use passed singleton if provided;
            # else legacy from_gcp (tests + backward compat preserved).
            if schwab_client is None:
                schwab_client = SchwabClient.from_gcp(
                    account_id=settings_obj.SCHWAB_ACCOUNT_ID,
                )
            live_builder = LiveSnapshotBuilder(schwab_client)
            logger.info(
                "ATLAS LiveSnapshotBuilder active (account_id=%s, TTL=30s)",
                settings_obj.SCHWAB_ACCOUNT_ID,
            )
            return CachedSnapshotBuilder(live_builder, ttl_seconds=30.0)
        except Exception:
            logger.exception(
                "USE_LIVE_PORTFOLIO=True but LiveSnapshotBuilder construction "
                "failed. Refusing to start. Set USE_LIVE_PORTFOLIO=False to "
                "fall back to DB-backed SnapshotBuilder."
            )
            raise

    # Default path: DB-backed (current behavior preserved).
    return CachedSnapshotBuilder(SnapshotBuilder(pool), ttl_seconds=5.0)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Initialize shared resources on startup; close on shutdown."""
    import asyncio
    from claude_router.router import ClaudeRouter
    from shared_core.storage.postgres_pool import PostgresPool
    from multi_agent.risk.config import load_buckets, load_limits
    from multi_agent.risk.portfolio_snapshot import (
        CachedSnapshotBuilder,
        LiveSnapshotBuilder,
        SnapshotBuilder,
    )
    from multi_agent.observability.llm_cost_repository import LLMCostRepository
    from multi_agent.persistence.system_repository import SystemRepository
    from multi_agent.alerts.bus import AlertBus
    from multi_agent.alerts.dedup import AlertDedup
    from multi_agent.alerts.repository import AlertRepository
    from multi_agent.alerts.retry_worker import RetryWorker
    from multi_agent.alerts.router import AlertRouter
    from multi_agent.alerts.sinks.telegram import TelegramSink
    from multi_agent.alerts.worker import AlertWorker
    from multi_agent.data_layer import SchwabDataLayer
    from multi_agent.persistence.iv_history_repository import IvHistoryRepository
    from multi_agent.persistence.iv_surface_repository import IvSurfaceRepository
    from multi_agent.persistence.ohlcv_repository import OhlcvRepository
    from multi_agent.workers.iv_history_worker import IvHistoryWorker
    from multi_agent.workers.ohlcv_worker import OhlcvWorker
    from shared_core.brokers.schwab_client import SchwabClient

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
    # F-r16 (Sprint 14 f-r16-a): SchwabClient singleton DI lifespan.
    # 4 instances → 1 singleton (resolves ADR-013 §9.3 #6 + ADR-005 §9.3 #1).
    app.state.schwab_client = _build_schwab_client(settings)
    if app.state.schwab_client is not None:
        logger.info(
            "✓ SchwabClient singleton ready (account_id=%s)",
            settings.SCHWAB_ACCOUNT_ID or "auto-discovery",
        )
    # ADR-010 D4 (Sprint 15 ws-a): SchwabStreamer singleton DI lifespan.
    app.state.schwab_streamer = _build_schwab_streamer(settings, app.state.schwab_client)
    if app.state.schwab_streamer is not None:
        try:
            await app.state.schwab_streamer.connect()
            logger.info("✓ SchwabStreamer singleton ready + connected")
        except Exception as e:
            logger.error("SchwabStreamer connect failed: %s", e)
            app.state.schwab_streamer = None  # graceful degradation Phase 1
    app.state.snapshot_builder = _build_snapshot_builder(
        settings, pool, schwab_client=app.state.schwab_client
    )
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

    # iv_history_repo: built unconditionally-conditional. When
    # USE_SCHWAB_DATA_LAYER=True, we instantiate now (before _select_data_layer)
    # so SchwabDataLayer + IvHistoryWorker share the same repo instance.
    # When False (StubDataLayer path), keep None — SchwabDataLayer fallback
    # path also accepts None per ADR-005 D5 (S.6.iv-d).
    iv_history_repo: IvHistoryRepository | None = None
    # iv_surface_repo + ohlcv_repo: Phase 2 consumer surface (S.10.cons-d,
    # ADR-009 D4). Consumed por SchwabDataLayer (READ) + IvHistoryWorker /
    # OhlcvWorker (WRITE). Construct shared instances before _select_data_layer
    # so SchwabDataLayer reads from same pool as workers write.
    iv_surface_repo: IvSurfaceRepository | None = None
    ohlcv_repo: OhlcvRepository | None = None
    if settings.USE_SCHWAB_DATA_LAYER:
        iv_history_repo = IvHistoryRepository(pool)
        iv_surface_repo = IvSurfaceRepository(pool)
        ohlcv_repo = OhlcvRepository(pool)
    app.state.iv_history_repo = iv_history_repo
    app.state.iv_surface_repo = iv_surface_repo
    app.state.ohlcv_repo = ohlcv_repo

    # ATHENA real agent dependencies (Sprint 3 B.3.5).
    # Config path: env override + project-root fallback (mirrors risk/config.py).
    default_router_config = (
        Path(__file__).resolve().parents[3]
        / "claude_router" / "config" / "routing_rules.yaml"
    )
    router_config_path = os.environ.get("CLAUDE_ROUTER_CONFIG", str(default_router_config))
    app.state.claude_router = ClaudeRouter.from_config(router_config_path)
    app.state.data_layer = _select_data_layer(
        settings,
        iv_history_repo=iv_history_repo,
        iv_surface_repo=iv_surface_repo,
        ohlcv_repo=ohlcv_repo,
        schwab_client=app.state.schwab_client,
    )
    logger.info(
        "✓ ATHENA dependencies ready: claude_router (config=%s), data_layer=%s",
        router_config_path,
        type(app.state.data_layer).__name__,
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

    # Worker chain (Sprint 4 B.4.5a) — consumers that process the debate
    # pipeline async after the trigger endpoint publishes a proposal.
    # ApolloConsumer reads PROPOSALS → APOLLO LLM → publishes CRITIQUES.
    # ConsensusConsumer reads CRITIQUES → consensus.evaluate → publishes
    # DECISIONS. AtlasConsumer reads DECISIONS → atlas_core.validate →
    # publishes ATLAS_VALIDATION. AtlasConsumer was migrated from
    # run_async_cycle.py to the API lifespan in B.4.5a (G1 decision);
    # running both processes in parallel is unsupported in Sprint 4.
    from multi_agent.consumers import ApolloConsumer, AtlasConsumer, ConsensusConsumer
    from multi_agent.persistence.message_repository import MessageRepository

    shared_repo = MessageRepository(pool)

    apollo_consumer = ApolloConsumer.build(
        bus=app.state.message_bus,
        repo=shared_repo,
        claude_router=app.state.claude_router,
        data_layer=app.state.data_layer,
    )
    apollo_consumer.start()
    app.state.apollo_consumer = apollo_consumer

    consensus_consumer = ConsensusConsumer.build(
        bus=app.state.message_bus,
        repo=shared_repo,
    )
    consensus_consumer.start()
    app.state.consensus_consumer = consensus_consumer

    atlas_consumer = AtlasConsumer.build(
        bus=app.state.message_bus,
        repo=shared_repo,
        pool=pool,
    )
    atlas_consumer.start()
    app.state.atlas_consumer = atlas_consumer

    # Spawn the daemon threads now that all subscriptions are registered.
    app.state.message_bus.start()
    logger.info("✓ Worker chain started: Apollo + Consensus + Atlas consumers")

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

    # ── IvHistoryWorker (Sprint 6 S.6.iv-c) ─────────────────────────────────
    # Conditional: only when USE_SCHWAB_DATA_LAYER active (D-η, fails closed).
    # F-r16 (Sprint 14 f-r16-a): worker uses singleton app.state.schwab_client
    # (resolves doble construcción tech debt ADR-005 §9.3 #1 + ADR-013 §9.3 #6).
    iv_worker = None
    iv_task = None
    if settings.USE_SCHWAB_DATA_LAYER and isinstance(app.state.data_layer, SchwabDataLayer):
        iv_worker = IvHistoryWorker(
            repo=app.state.iv_history_repo,
            schwab_client=app.state.schwab_client,
            surface_repo=app.state.iv_surface_repo,
        )
        iv_task = asyncio.create_task(iv_worker.run())
        app.state.iv_worker = iv_worker
        logger.info("✓ IvHistoryWorker active (snapshot 21:15 UTC daily)")
        if app.state.iv_surface_repo is not None:
            logger.info(
                "✓ iv_surface populating enabled (per snapshot, D3-1 isolated)"
            )

    # ── OhlcvWorker (Sprint 9 S.9.ohl-b, ADR-007 D3) ────────────────────────
    # Stagger from IvHistoryWorker 21:15 UTC → 21:30 UTC (F-r7 mitigation).
    # F-r16 (Sprint 14 f-r16-a): worker uses singleton app.state.schwab_client
    # (resolves doble construcción tech debt ADR-005 §9.3 #1 + ADR-013 §9.3 #6).
    # OhlcvRepository shared con SchwabDataLayer via app.state.ohlcv_repo.
    ohlcv_worker = None
    ohlcv_task = None
    if settings.USE_SCHWAB_DATA_LAYER and isinstance(app.state.data_layer, SchwabDataLayer):
        ohlcv_worker = OhlcvWorker(
            repo=app.state.ohlcv_repo,
            schwab_client=app.state.schwab_client,
        )
        ohlcv_task = asyncio.create_task(ohlcv_worker.run())
        app.state.ohlcv_worker = ohlcv_worker
        logger.info("✓ OhlcvWorker active (snapshot 21:30 UTC daily, 4 timeframes)")

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

    # ADR-010 D4 (Sprint 15 ws-a): SchwabStreamer cleanup
    if getattr(app.state, "schwab_streamer", None) is not None:
        try:
            await app.state.schwab_streamer.disconnect()
        except Exception:
            logger.exception("SchwabStreamer disconnect error (continuing)")

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
    if iv_worker is not None:
        iv_worker.shutdown()
    if ohlcv_worker is not None:
        ohlcv_worker.shutdown()
    tasks_to_gather = [worker_task, retry_task]
    if iv_task is not None:
        tasks_to_gather.append(iv_task)
    if ohlcv_task is not None:
        tasks_to_gather.append(ohlcv_task)
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks_to_gather, return_exceptions=True),
            timeout=10.0,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.warning("Alert workers did not stop cleanly within 10s")

    # Stop worker chain threads first (so in-flight messages complete
    # before Redis closes underneath them).
    try:
        app.state.message_bus.stop()
        logger.info("Worker chain stopped (Apollo + Consensus + Atlas)")
    except Exception:
        logger.exception("Worker chain shutdown error (continuing)")

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
