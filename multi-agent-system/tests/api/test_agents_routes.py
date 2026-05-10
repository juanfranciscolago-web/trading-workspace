"""
Unit tests for agents API routes.
No DB — AgentsRepository is mocked via FastAPI dependency overrides.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ── Test data ─────────────────────────────────────────────────────────────────

_AGENT_ROW_APOLLO = {
    "agent_id": "apollo",
    "display_name": "APOLLO",
    "role": "Macro discrecional",
    "time_horizon_min_days": 14,
    "time_horizon_max_days": 180,
    "default_llm_model": "claude-sonnet-4-6",
    "max_portfolio_pct": "20.00",
    "is_active": True,
    "status": "idle",
    "current_task": None,
    "last_heartbeat": None,
    "last_proposal_at": None,
    "last_error": None,
    "error_count_24h": 0,
    "llm_cost_today_usd": "0.0000",
}

_AGENT_ROW_ATHENA = {
    **_AGENT_ROW_APOLLO,
    "agent_id": "athena",
    "display_name": "ATHENA",
    "role": "Cuantitativa sistemática",
    "time_horizon_min_days": 15,
    "time_horizon_max_days": 45,
}

_ALL_AGENTS = [_AGENT_ROW_APOLLO, _AGENT_ROW_ATHENA]


def _make_client(agents=None, set_active_result=True):
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_agents_repo

    app = create_app()
    mock_repo = MagicMock()
    mock_repo.list_agents.return_value = agents if agents is not None else list(_ALL_AGENTS)
    mock_repo.set_active.return_value = set_active_result

    app.dependency_overrides[get_agents_repo] = lambda: mock_repo
    return TestClient(app), mock_repo


def _make_client_with_mocks(
    proposal_response_text: str | None = None,
):
    """Build a TestClient with the 3 trigger-endpoint deps mocked.

    Returns (client, mock_router, mock_data_layer, mock_message_repo).
    """
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import (
        get_claude_router,
        get_data_layer,
        get_message_repo,
    )

    app = create_app()

    mock_router = MagicMock()
    if proposal_response_text is not None:
        response = MagicMock()
        response.text = proposal_response_text
        response.model_used = "claude-sonnet-4-6"
        response.request_id = "test-req-trigger"
        response.cost = MagicMock(total_usd=0.001)
        mock_router.send.return_value = response

    mock_data_layer = MagicMock()
    mock_state = MagicMock()
    mock_state.timestamp = datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)
    mock_state.tickers = {}
    mock_state.correlations = {}
    mock_state.to_dict.return_value = {
        "timestamp": mock_state.timestamp.isoformat(),
        "tickers": {},
        "correlations": {},
    }
    mock_data_layer.snapshot.return_value = mock_state

    mock_message_repo = MagicMock()

    app.dependency_overrides[get_claude_router] = lambda: mock_router
    app.dependency_overrides[get_data_layer] = lambda: mock_data_layer
    app.dependency_overrides[get_message_repo] = lambda: mock_message_repo

    return TestClient(app), mock_router, mock_data_layer, mock_message_repo


# ── GET /agents ───────────────────────────────────────────────────────────────

class TestListAgents:

    def test_returns_200(self):
        client, _ = _make_client()
        assert client.get("/agents").status_code == 200

    def test_items_count(self):
        client, _ = _make_client()
        data = client.get("/agents").json()
        assert len(data["items"]) == 2

    def test_item_shape(self):
        client, _ = _make_client()
        item = client.get("/agents").json()["items"][0]
        for field in ("agent_id", "display_name", "is_active", "status", "llm_cost_today_usd"):
            assert field in item

    def test_empty_list(self):
        client, _ = _make_client(agents=[])
        data = client.get("/agents").json()
        assert data["items"] == []

    def test_inactive_agent_reflected(self):
        inactive = {**_AGENT_ROW_APOLLO, "is_active": False}
        client, _ = _make_client(agents=[inactive])
        item = client.get("/agents").json()["items"][0]
        assert item["is_active"] is False


# ── POST /agents/{agent_id}/toggle ────────────────────────────────────────────

class TestToggleAgent:

    def test_returns_200(self):
        client, _ = _make_client()
        r = client.post("/agents/apollo/toggle", json={"is_active": False})
        assert r.status_code == 200

    def test_response_shape(self):
        client, _ = _make_client()
        data = client.post("/agents/apollo/toggle", json={"is_active": False}).json()
        assert data["agent_id"] == "apollo"
        assert data["is_active"] is False

    def test_set_active_called_with_correct_args(self):
        client, mock_repo = _make_client()
        client.post("/agents/apollo/toggle", json={"is_active": False})
        mock_repo.set_active.assert_called_once_with("apollo", False)

    def test_unknown_agent_returns_404(self):
        client, _ = _make_client(set_active_result=False)
        r = client.post("/agents/unknown/toggle", json={"is_active": False})
        assert r.status_code == 404

    def test_404_detail_contains_agent_id(self):
        client, _ = _make_client(set_active_result=False)
        r = client.post("/agents/unknown/toggle", json={"is_active": False})
        assert "unknown" in r.json()["detail"]

    def test_activate_agent(self):
        client, mock_repo = _make_client()
        r = client.post("/agents/athena/toggle", json={"is_active": True})
        assert r.status_code == 200
        assert r.json()["is_active"] is True
        mock_repo.set_active.assert_called_once_with("athena", True)


# ── POST /agents/athena/trigger ───────────────────────────────────────────────

_SHAPE_A_JSON = json.dumps({
    "trade": {
        "ticker": "SPY",
        "asset_class": "option",
        "strategy_type": "CSP",
        "structure": {
            "legs": [{
                "action": "sell",
                "instrument_type": "put",
                "strike": "425.0",
                "expiration": "2026-06-15",
                "quantity": 1,
            }],
            "estimated_credit": "3.50",
            "estimated_debit": None,
            "max_profit": "3.50",
            "max_loss": "421.50",
            "breakeven": "421.50",
            "buying_power_required": "42500.0",
        },
    },
    "thesis": {
        "premise": "SPY IV elevated relative to realized vol",
        "mechanism": "Sell ATM put, collect theta",
        "key_data_points": ["IV rank 65", "30d realized 18%"],
        "invalidation": "SPY closes below short strike",
        "target": "Close at 50% max profit",
        "time_horizon_days": 30,
        "expected_holding_period_days": 21,
    },
    "conviction_score": 72,
    "sizing": {
        "proposed_size_pct_portfolio": 2.5,
        "proposed_size_usd": "25000.0",
        "kelly_suggested": 0.30,
        "kelly_fraction_applied": 0.25,
    },
    "self_acknowledged_biases": ["recency_bias_on_IV"],
})

_SHAPE_B_JSON = json.dumps({
    "no_setup": True,
    "reason": "All IV ranks below 50; no selling opportunities.",
})


class TestAthenaTrigger:

    def test_trigger_shape_a_returns_proposal(self):
        client, _, _, _ = _make_client_with_mocks(_SHAPE_A_JSON)
        r = client.post("/agents/athena/trigger")
        assert r.status_code == 200
        data = r.json()
        assert data["no_setup"] is False
        assert data["proposal"] is not None
        assert data["proposal"]["trade"]["ticker"] == "SPY"

    def test_trigger_shape_a_persists_proposal(self):
        client, _, _, mock_message_repo = _make_client_with_mocks(_SHAPE_A_JSON)
        client.post("/agents/athena/trigger")
        mock_message_repo.save_proposal.assert_called_once()

    def test_trigger_shape_b_returns_no_setup(self):
        client, _, _, _ = _make_client_with_mocks(_SHAPE_B_JSON)
        r = client.post("/agents/athena/trigger")
        assert r.status_code == 200
        data = r.json()
        assert data["no_setup"] is True
        assert data["proposal"] is None

    def test_trigger_shape_b_does_not_persist(self):
        client, _, _, mock_message_repo = _make_client_with_mocks(_SHAPE_B_JSON)
        client.post("/agents/athena/trigger")
        mock_message_repo.save_proposal.assert_not_called()

    def test_trigger_correlation_id_propagated(self):
        client, _, _, _ = _make_client_with_mocks(_SHAPE_A_JSON)
        data = client.post("/agents/athena/trigger").json()
        # Top-level correlation_id matches the proposal's correlation_id
        assert data["correlation_id"] == data["proposal"]["correlation_id"]
