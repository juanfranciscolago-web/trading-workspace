#!/usr/bin/env python3
"""
run_async_cycle.py — Flujo async completo con ATLAS real.

Levanta:
  - AtlasConsumer (reads agent.decisions, runs ATLAS core, publishes atlas_validations)
  - PaperExecutor (reads agent.atlas_validations, simulates execution)
  - DlqConsumer   (reads *.dead_letter streams, persists to rejected_dlq)

Luego corre N ciclos del mock orchestrator para generar mensajes de prueba.

Requisitos:
  DATABASE_URL: postgresql://trader:trader@localhost:5432/trading
  REDIS_URL:    redis://localhost:6379/0 (default)

Uso:
  python run_async_cycle.py                          # 1 ciclo, scenario all_agree
  python run_async_cycle.py --cycles 5               # 5 ciclos
  python run_async_cycle.py --scenario atlas_blocks  # escenario específico
  python run_async_cycle.py --smoke-test             # verifica setup sin ciclos
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_async_cycle")


def _require_env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        print(f"ERROR: {name} env var is required. Set it before running.", file=sys.stderr)
        sys.exit(1)
    return val


def main() -> None:
    parser = argparse.ArgumentParser(description="Async cycle runner with real ATLAS")
    parser.add_argument("--cycles", type=int, default=1, help="Number of cycles to run")
    parser.add_argument(
        "--scenario",
        default="all_agree",
        choices=["all_agree", "nyx_dissents", "deep_disagreement", "atlas_blocks", "high_conviction_solo"],
    )
    parser.add_argument("--smoke-test", action="store_true", help="Just verify setup, no cycles")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    db_url = _require_env("DATABASE_URL", "postgresql://trader:trader@localhost:5432/trading")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    logger.info("Connecting to DB: %s", db_url.split("@")[-1])
    logger.info("Connecting to Redis: %s", redis_url)

    # ── Imports ────────────────────────────────────────────────────────────────
    try:
        import redis
        from shared_core.storage.postgres_pool import PostgresPool

        from multi_agent.agents import SCENARIOS, build_orchestrator
        from multi_agent.communication.message_bus import AgentMessageBus
        from multi_agent.consumers import AtlasConsumer, DlqConsumer
        from multi_agent.execution import PaperExecutor
        from multi_agent.persistence import MessageRepository
    except ImportError as exc:
        print(f"Import error: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Setup ──────────────────────────────────────────────────────────────────
    pool = PostgresPool(dsn=db_url)
    repo = MessageRepository(pool)

    redis_client = redis.from_url(redis_url, decode_responses=False)
    bus = AgentMessageBus(redis_client)

    proposal_cache: dict = {}

    atlas_consumer = AtlasConsumer.build(bus, repo, pool, proposal_cache)
    paper_executor = PaperExecutor(bus, repo, proposal_cache)
    dlq_consumer = DlqConsumer(redis_client, repo)

    if args.smoke_test:
        logger.info("Smoke test: setup OK — consumers wired, not starting bus")
        print("✓ Smoke test passed — all components initialized successfully")
        return

    # ── Start consumers ────────────────────────────────────────────────────────
    atlas_consumer.start()
    paper_executor.start()
    dlq_consumer.start()
    bus.start()
    logger.info("Bus and consumers started")

    # ── Run mock cycles ────────────────────────────────────────────────────────
    class PublishingRepo:
        """Wraps MessageRepository + publishes each message to the bus."""
        def __init__(self, inner_repo, inner_bus, inner_proposal_cache):
            self._repo = inner_repo
            self._bus = inner_bus
            self._cache = inner_proposal_cache

        def save_proposal(self, msg, **_):
            self._repo.save_proposal(msg)
            from multi_agent.communication.message_bus import AgentChannels
            self._bus.publish(AgentChannels.PROPOSALS, msg)
            self._cache[str(msg.correlation_id)] = msg

        def save_critique(self, msg, **_):
            self._repo.save_critique(msg)
            from multi_agent.communication.message_bus import AgentChannels
            self._bus.publish(AgentChannels.CRITIQUES, msg)

        def save_decision(self, msg, **_):
            self._repo.save_decision(msg)
            from multi_agent.communication.message_bus import AgentChannels
            self._bus.publish(AgentChannels.DECISIONS, msg)

        def save_atlas_validation(self, msg, **_):
            pass  # handled by AtlasConsumer

        def log_llm_cost(self, **_):
            pass

    pub_repo = PublishingRepo(repo, bus, proposal_cache)
    orchestrator = build_orchestrator(pub_repo)
    scenario = SCENARIOS[args.scenario]

    logger.info("Running %d cycle(s) with scenario '%s'", args.cycles, args.scenario)
    for i in range(args.cycles):
        seed = args.seed if args.seed is not None else scenario.seed + i
        result = orchestrator.run_cycle(scenario, seed=seed)
        logger.info(
            "Cycle %d/%d: corr=%s ticker=%s decision=%s",
            i + 1,
            args.cycles,
            str(result.correlation_id)[:8],
            result.proposal.trade.ticker,
            result.decision.outcome.value,
        )
        # Give async consumers time to process
        time.sleep(0.5)

    # Wait for processing to complete
    logger.info("Waiting 3s for consumers to finish processing...")
    time.sleep(3.0)

    bus.stop()
    dlq_consumer.stop()
    logger.info("Done — check DB for results")


if __name__ == "__main__":
    main()
