"""
End-to-end integration test for the ATHENA proposal flow (Sprint 3 B.3.7).

Tests cover the full pipeline with ALL real components except the LLM:
- Real PostgresPool (skipped if PG not available)
- Real StubDataLayer (provides market state)
- Real MessageRepository (writes/reads trades.proposals)
- Real AthenaAgent
- Real FastAPI routes (via TestClient with lifespan)
- ONLY ClaudeRouter is mocked (canned LLM responses)

Two paths covered:
1. Shape A (happy path):  trigger → LLM returns proposal → save in DB →
   list shows it (with persisted time_horizon_days) → detail reconstructs
   full ProposalMessage.
2. Shape B (no_setup):    trigger → LLM declines → NO save → detail 404 +
   direct DB COUNT(*) = 0.

Uses IWM iron condor for Shape A — different values from other test
fixtures (SPY CSP in test_athena_agent.py, QQQ credit spread in
proposal_shape.json) to keep this fixture independent.

NOTE: Each test creates a real row in trades.proposals. The DB grows over
time across runs. correlation_id is server-generated (uuid4) so collisions
are impossible. No cleanup — matches the existing integration test pattern
in test_message_repository.py.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from multi_agent.config import settings


@pytest.fixture(scope="module", autouse=True)
def _require_db():
    """Skip all tests in this module if PostgreSQL is not available."""
    try:
        conn = psycopg.connect(settings.DATABASE_URL, connect_timeout=3)
        conn.close()
    except Exception:
        pytest.skip("PostgreSQL not available — skipping ATHENA E2E tests")


# ── Canned LLM responses — third unique fixture set ───────────────────────────

_SHAPE_A_IWM_IRON_CONDOR = json.dumps({
    "trade": {
        "ticker": "IWM",
        "asset_class": "option",
        "strategy_type": "IRON_CONDOR",
        "structure": {
            "legs": [
                {"action": "sell", "instrument_type": "put",  "strike": "190.0", "expiration": "2026-06-19", "quantity": 1},
                {"action": "buy",  "instrument_type": "put",  "strike": "185.0", "expiration": "2026-06-19", "quantity": 1},
                {"action": "sell", "instrument_type": "call", "strike": "215.0", "expiration": "2026-06-19", "quantity": 1},
                {"action": "buy",  "instrument_type": "call", "strike": "220.0", "expiration": "2026-06-19", "quantity": 1},
            ],
            "estimated_credit": "1.85",
            "estimated_debit": None,
            "max_profit": "1.85",
            "max_loss": "3.15",
            "breakeven": "188.15",
            "buying_power_required": "500.0",
        },
    },
    "thesis": {
        "premise": "IWM range-bound; high IV percentile post-earnings",
        "mechanism": "Iron condor profits from theta decay within IV range",
        "key_data_points": ["IV percentile 70", "30d realized 19%", "ATM straddle 4%"],
        "invalidation": "IWM breaks above 215 or below 190",
        "target": "Close at 50% max profit",
        "time_horizon_days": 35,
        "expected_holding_period_days": 25,
    },
    "conviction_score": 58,
    "sizing": {
        "proposed_size_pct_portfolio": 0.8,
        "proposed_size_usd": "8000.0",
        "kelly_suggested": 0.10,
        "kelly_fraction_applied": 0.08,
    },
    "self_acknowledged_biases": ["volatility_clustering_assumption"],
})

_SHAPE_B_NO_SETUP = json.dumps({
    "no_setup": True,
    "reason": "All IV percentiles below threshold; no premium selling opportunities (E2E test fixture).",
})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_app_with_mocked_router(llm_response_text: str):
    """Build an app with ONLY ClaudeRouter mocked; everything else is real."""
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_claude_router

    mock_router = MagicMock()
    response = MagicMock()
    response.text = llm_response_text
    response.model_used = "claude-sonnet-4-6"
    response.request_id = "test-e2e"
    response.cost = MagicMock(total_usd=0.001)
    mock_router.send.return_value = response

    app = create_app()
    app.dependency_overrides[get_claude_router] = lambda: mock_router
    return app


def _count_proposals_with_corr_id(corr_id: str) -> int:
    """Direct DB query — returns the number of rows in trades.proposals
    matching this correlation_id. Used for ground-truth persistence checks."""
    with psycopg.connect(settings.DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM trades.proposals WHERE correlation_id = %s",
                (corr_id,),
            )
            return cur.fetchone()[0]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAthenaE2EShapeA:

    def test_full_happy_path(self):
        """Trigger → DB persists → list contains → detail reconstructs full ProposalMessage."""
        app = _make_app_with_mocked_router(_SHAPE_A_IWM_IRON_CONDOR)

        with TestClient(app) as client:
            # 1. Trigger ATHENA
            r_trigger = client.post("/agents/athena/trigger")
            assert r_trigger.status_code == 200
            trigger_data = r_trigger.json()
            assert trigger_data["no_setup"] is False
            assert trigger_data["proposal"] is not None
            corr_id = trigger_data["correlation_id"]

            # 2. List endpoint includes the just-saved proposal
            r_list = client.get("/trades/proposals?limit=100")
            assert r_list.status_code == 200
            list_data = r_list.json()
            corr_ids = [item["correlation_id"] for item in list_data["items"]]
            assert corr_id in corr_ids, f"Triggered proposal {corr_id} not found in list"

            # Verify the save_proposal fix: time_horizon_days is persisted to the column
            list_item = next(i for i in list_data["items"] if i["correlation_id"] == corr_id)
            assert list_item["time_horizon_days"] == 35, (
                f"time_horizon_days should be 35 (from Shape A fixture), got {list_item['time_horizon_days']}"
            )

            # 3. Detail endpoint reconstructs the full ProposalMessage
            r_detail = client.get(f"/trades/proposals/{corr_id}")
            assert r_detail.status_code == 200
            detail_data = r_detail.json()
            assert detail_data["correlation_id"] == corr_id
            assert detail_data["agent_id"] == "ATHENA"
            assert detail_data["trade"]["ticker"] == "IWM"
            assert detail_data["trade"]["strategy_type"] == "IRON_CONDOR"
            assert len(detail_data["trade"]["structure"]["legs"]) == 4
            assert detail_data["conviction_score"] == 58


class TestAthenaE2EShapeB:

    def test_no_setup_skips_persistence(self):
        """Trigger → LLM declines → NO save in DB → detail 404 + direct DB COUNT = 0."""
        app = _make_app_with_mocked_router(_SHAPE_B_NO_SETUP)

        with TestClient(app) as client:
            # 1. Trigger ATHENA
            r_trigger = client.post("/agents/athena/trigger")
            assert r_trigger.status_code == 200
            trigger_data = r_trigger.json()
            assert trigger_data["no_setup"] is True
            assert trigger_data["proposal"] is None
            corr_id = trigger_data["correlation_id"]

            # 2. Detail endpoint returns 404 (route-layer evidence of no save)
            r_detail = client.get(f"/trades/proposals/{corr_id}")
            assert r_detail.status_code == 404
            assert r_detail.json()["detail"] == "proposal not found"

            # 3. Direct DB query confirms no row was written (ground truth)
            assert _count_proposals_with_corr_id(corr_id) == 0
