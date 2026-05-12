"""
End-to-end integration test for the Sprint 4 worker chain (B.4.5b).

Tests the full debate pipeline runs end-to-end after the trigger endpoint:

  POST /agents/athena/trigger
    → ProposalMessage published to agent.proposals
    → ApolloConsumer consumes (B.4.5a)
    → ApolloAgent.critique_proposal returns a critique via mocked LLM
    → CritiqueMessage saved + published to agent.critiques
    → ConsensusConsumer consumes (B.4.5a)
    → consensus.evaluate produces a DecisionMessage
    → DecisionMessage saved + published to agent.decisions
    → AtlasConsumer consumes (existing, migrated to lifespan in B.4.5a)
    → atlas_validate produces an AtlasValidationMessage
    → AtlasValidationMessage saved + published to agent.atlas_validations

Mocks ONLY the ClaudeRouter (canned ATHENA and APOLLO responses dispatched
by task_type). Real Postgres, real Redis, real consumers in lifespan.

ADR-003 called this sub-block "FakeRedis integration" but in practice
FakeRedis cannot be substituted without invasive refactor (the lifespan
calls redis.from_url(settings.REDIS_URL) directly with no injection
seam). Mirroring the test_athena_e2e.py pattern of "real services,
skip-if-unavailable" is the lower-friction path. FakeRedis-based testing
remains future work if real-Redis test latency becomes a problem.

Caveats:
- AtlasConsumer does NOT yet transition trades.proposals.status to
  'atlas_validated' after validation (B.4.5a gap). Status stays at
  'decided' (set by ConsensusConsumer). The test asserts the actual
  current behavior; when AtlasConsumer adds the status transition,
  this test must update accordingly.
- If SnapshotBuilder fails on an empty positions table, the chain
  may stop at decision (no atlas_validation row). If this happens
  in practice, the test will time out at the atlas_validations wait
  and the test must descope to a 3-step chain (proposal+critique+decision).
- Running run_async_cycle.py in parallel with this test would cause
  consumer_name conflicts in Redis Streams. Run pytest in isolation.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import psycopg
import pytest
import redis
from fastapi.testclient import TestClient

from multi_agent.config import settings


@pytest.fixture(scope="module", autouse=True)
def _require_db_and_redis():
    """Skip all tests in this module if Postgres or Redis is unavailable."""
    try:
        conn = psycopg.connect(settings.DATABASE_URL, connect_timeout=3)
        conn.close()
    except Exception:
        pytest.skip("PostgreSQL not available — skipping pipeline E2E tests")
    try:
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
        r.close()
    except Exception:
        pytest.skip("Redis not available — skipping pipeline E2E tests")


# ── Canned LLM responses dispatched by task_type ──────────────────────────────

_ATHENA_PROPOSAL_JSON = json.dumps({
    "trade": {
        "ticker": "QQQ",  # unique ticker for this fixture vs other E2E tests
        "asset_class": "option",
        "strategy_type": "CSP",
        "structure": {
            "legs": [{
                "action": "sell",
                "instrument_type": "put",
                "strike": "490.0",
                "expiration": "2026-06-19",
                "quantity": 1,
            }],
            "estimated_credit": "5.20",
            "estimated_debit": None,
            "max_profit": "520.0",
            "max_loss": "48480.0",
            "breakeven": "484.80",
            "buying_power_required": "49000.0",
        },
    },
    "thesis": {
        "premise": "QQQ IV elevated; mean reversion likely",
        "mechanism": "Sell ATM put, collect theta in low-vol regime",
        "key_data_points": ["IV rank 62", "ATM straddle 3.5%"],
        "invalidation": "QQQ closes below 485",
        "target": "Close at 50% max profit",
        "time_horizon_days": 30,
        "expected_holding_period_days": 21,
    },
    "conviction_score": 68,
    "sizing": {
        "proposed_size_pct_portfolio": 1.5,
        "proposed_size_usd": "15000.0",
        "kelly_suggested": 0.20,
        "kelly_fraction_applied": 0.15,
    },
    "self_acknowledged_biases": [],
})

_APOLLO_CRITIQUE_JSON = json.dumps({
    "stance": "AGREE",
    "argument": {
        "summary": "Macro backdrop supports premium-selling on QQQ",
        "evidence": [
            {"claim": "VIX below 18", "data_source": "cboe", "value": "16.5"},
            {"claim": "Fed pause priced in", "data_source": "fed_funds_futures", "value": "0.85"},
        ],
        "concern": "FOMC meeting falls outside the DTE window — manageable",
        "data_that_would_change_my_mind": "VIX spike above 25 within DTE",
    },
    "veto_request": False,
    "contrarian_flag_raised": False,
    "alternative_proposal": None,
})


def _patched_router_send(self, *, task_type, **kwargs):
    """Replacement for ClaudeRouter.send (instance method — self is ignored;
    we route purely on task_type). Returns different canned responses for
    ATHENA (proposal_generation) and APOLLO (cross_examination).

    This patches the ClaudeRouter CLASS method rather than overriding the
    FastAPI dep — necessary because the consumers (ApolloConsumer in lifespan)
    hold a real ClaudeRouter instance and don't go through get_claude_router
    dep injection. Class-method patching covers BOTH paths: the HTTP route
    that uses get_claude_router AND the daemon-thread consumers that use
    app.state.claude_router."""
    response = MagicMock()
    response.model_used = "claude-sonnet-4-6"
    response.request_id = f"test-pipeline-{task_type}"
    response.cost = MagicMock(total_usd=0.001)
    if task_type == "proposal_generation":
        response.text = _ATHENA_PROPOSAL_JSON
    elif task_type == "cross_examination":
        response.text = _APOLLO_CRITIQUE_JSON
    else:
        raise ValueError(f"unexpected task_type in pipeline E2E test: {task_type}")
    return response


def _clear_streams() -> None:
    """Delete all agent.* streams in Redis to start the test from a clean
    state. Necessary because daemon threads replay pending messages on
    startup, and stale messages from prior runs (failed tests, smoke runs)
    can block the chain by occupying consumer threads with old work."""
    r = redis.from_url(settings.REDIS_URL)
    for stream in (
        "agent.proposals",
        "agent.critiques",
        "agent.decisions",
        "agent.atlas_validations",
    ):
        r.delete(stream)
    r.close()


def _make_app():
    """Build an app — no dep override needed because we patch ClaudeRouter
    at the class level (see _patched_router_send)."""
    from multi_agent.api.app import create_app
    return create_app()


def _wait_for(predicate, *, timeout: float = 15.0, interval: float = 0.2) -> None:
    """Poll predicate every `interval` seconds until it returns truthy or
    timeout. Raises TimeoutError on expiry. Exceptions in predicate are
    swallowed (treated as 'not ready yet')."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            if predicate():
                return
        except Exception:
            pass
        time.sleep(interval)
    raise TimeoutError(f"predicate did not become true within {timeout}s")


def _count_table_rows(table: str, corr_id: str) -> int:
    """Direct DB row count for a (table, correlation_id) pair. Ground truth
    for chain-progress assertions."""
    with psycopg.connect(settings.DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM trades.{table} WHERE correlation_id = %s",
                (corr_id,),
            )
            return cur.fetchone()[0]


def _query_status(corr_id: str) -> str | None:
    with psycopg.connect(settings.DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM trades.proposals WHERE correlation_id = %s",
                (corr_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def _cleanup_pipeline_rows(corr_id: str) -> None:
    """Delete all rows for corr_id in reverse FK order. Used in test
    finally blocks to keep tests isolated and the DB clean across runs."""
    with psycopg.connect(settings.DATABASE_URL) as conn:
        with conn.cursor() as cur:
            for table in ("atlas_validations", "decisions", "critiques", "proposals"):
                cur.execute(
                    f"DELETE FROM trades.{table} WHERE correlation_id = %s",
                    (corr_id,),
                )
        conn.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPipelineE2E:

    def test_pipeline_full_chain_proposal_to_atlas_validation(self, monkeypatch):
        """Trigger ATHENA → wait for AtlasConsumer to produce a validation row →
        verify all 4 tables have 1 row each with the same correlation_id."""
        # Class-level patch so both HTTP-route ATHENA and daemon-thread
        # APOLLO use the canned responses.
        from claude_router.router import ClaudeRouter
        monkeypatch.setattr(ClaudeRouter, "send", _patched_router_send)

        # Clean slate: previous failed tests or smoke runs may have left
        # pending messages in the streams that would clog the consumers.
        _clear_streams()

        app = _make_app()
        corr_id = None
        try:
            with TestClient(app) as client:
                # 1. Trigger ATHENA. Endpoint returns once the proposal is in
                # DB and on the bus; the chain runs async in daemon threads.
                r = client.post("/agents/athena/trigger")
                assert r.status_code == 200
                data = r.json()
                assert data["no_setup"] is False
                corr_id = data["correlation_id"]

                # 2. Wait for the chain to complete. The terminal signal is
                # 1 row in trades.atlas_validations for this correlation_id.
                _wait_for(
                    lambda: _count_table_rows("atlas_validations", corr_id) == 1,
                    timeout=15.0,
                )

                # 3. All 4 tables have exactly 1 row with this correlation_id.
                assert _count_table_rows("proposals", corr_id) == 1
                assert _count_table_rows("critiques", corr_id) == 1
                assert _count_table_rows("decisions", corr_id) == 1
                assert _count_table_rows("atlas_validations", corr_id) == 1

                # 4. Status reflects current real behavior: ConsensusConsumer
                # set it to 'decided'. AtlasConsumer does NOT yet transition
                # to 'atlas_validated' (B.4.5a gap, tech debt registered).
                # When that gap is closed, update this assertion.
                assert _query_status(corr_id) == "decided"
        finally:
            if corr_id:
                _cleanup_pipeline_rows(corr_id)
