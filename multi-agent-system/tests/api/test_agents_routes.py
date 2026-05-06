"""
Unit tests for agents API routes.
No DB — AgentsRepository is mocked via FastAPI dependency overrides.
"""
from __future__ import annotations

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
