"""
Unit tests for cost API routes.
No DB — LLMCostRepository is mocked via FastAPI dependency overrides.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

_EMPTY_SUMMARY = {
    "total_cost_usd": 0.0,
    "total_tokens": 0,
    "total_calls": 0,
    "by_model": [],
    "period_days": 7,
}

_SUMMARY_WITH_DATA = {
    "total_cost_usd": 1.25,
    "total_tokens": 5000,
    "total_calls": 3,
    "by_model": [{"model_used": "claude-sonnet-4-6", "calls": 3, "cost_usd": 1.25, "total_tokens": 5000}],
    "period_days": 7,
}

_AGENT_ROWS = [{"agent_id": "ATHENA", "calls": 2, "cost_usd": 0.80, "total_tokens": 3000, "cache_read_ratio": 0.1}]
_TASK_ROWS = [{"task_type": "market_analysis", "calls": 2, "cost_usd": 0.80, "avg_tokens": 1500.0}]
_DAILY_ROWS = [{"date": "2026-04-29", "calls": 2, "cost_usd": 0.80, "total_tokens": 3000}]


def _make_client(summary=None, agent_rows=None, task_rows=None, daily_rows=None):
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_cost_repo

    app = create_app()
    mock_repo = MagicMock()
    mock_repo.get_summary_by_period.return_value = summary or _EMPTY_SUMMARY
    mock_repo.get_by_agent.return_value = agent_rows or []
    mock_repo.get_by_task.return_value = task_rows or []
    mock_repo.get_daily_totals.return_value = daily_rows or []

    app.dependency_overrides[get_cost_repo] = lambda: mock_repo
    return TestClient(app), mock_repo


# ── GET /costs/summary ────────────────────────────────────────────────────────

class TestCostSummary:

    def test_returns_200(self):
        client, _ = _make_client()
        assert client.get("/costs/summary").status_code == 200

    def test_has_total_cost_usd(self):
        client, _ = _make_client(summary=_SUMMARY_WITH_DATA)
        data = client.get("/costs/summary").json()
        assert data["total_cost_usd"] == pytest.approx(1.25)

    def test_period_days_reflected(self):
        client, _ = _make_client()
        data = client.get("/costs/summary").json()
        assert data["period_days"] == 7

    def test_custom_days_param_forwarded(self):
        client, mock_repo = _make_client()
        client.get("/costs/summary?days=14")
        mock_repo.get_summary_by_period.assert_called_once_with(days=14)

    def test_empty_summary_returns_zeros(self):
        client, _ = _make_client(summary=_EMPTY_SUMMARY)
        data = client.get("/costs/summary").json()
        assert data["total_calls"] == 0
        assert data["total_cost_usd"] == pytest.approx(0.0)


# ── GET /costs/by-agent ───────────────────────────────────────────────────────

class TestCostByAgent:

    def test_returns_200(self):
        client, _ = _make_client()
        assert client.get("/costs/by-agent").status_code == 200

    def test_has_rows_field(self):
        client, _ = _make_client(agent_rows=_AGENT_ROWS)
        data = client.get("/costs/by-agent").json()
        assert "rows" in data
        assert len(data["rows"]) == 1
        assert data["rows"][0]["agent_id"] == "ATHENA"


# ── GET /costs/by-task ────────────────────────────────────────────────────────

class TestCostByTask:

    def test_returns_200(self):
        client, _ = _make_client()
        assert client.get("/costs/by-task").status_code == 200

    def test_has_rows_field(self):
        client, _ = _make_client(task_rows=_TASK_ROWS)
        data = client.get("/costs/by-task").json()
        assert "rows" in data
        assert data["rows"][0]["task_type"] == "market_analysis"


# ── GET /costs/daily ──────────────────────────────────────────────────────────

class TestCostDaily:

    def test_returns_200(self):
        client, _ = _make_client()
        assert client.get("/costs/daily").status_code == 200

    def test_has_rows_field(self):
        client, _ = _make_client(daily_rows=_DAILY_ROWS)
        data = client.get("/costs/daily").json()
        assert "rows" in data
        assert data["rows"][0]["date"] == "2026-04-29"
