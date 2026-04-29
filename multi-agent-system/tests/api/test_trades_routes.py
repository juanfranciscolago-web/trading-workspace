"""
Unit tests for trades API routes.
No DB — ValidationRepository is mocked via FastAPI dependency overrides.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

_VALID_UUID = "12345678-1234-5678-1234-567812345678"

_SAMPLE_ROW = {
    "correlation_id": _VALID_UUID,
    "approved": True,
    "executed_size_pct": 5.0,
    "original_size_pct": 5.0,
    "reason": "approved:ok",
    "atlas_version": "atlas-1.0",
    "portfolio_snapshot_id": "a" * 64,
    "evaluation_time_ms": 1.5,
    "checks_passed": ["pnl_ok", "bp_ok"],
    "checks_failed": [],
    "risk_mode": "GREEN",
    "created_at": datetime(2026, 4, 29, 14, 0, tzinfo=timezone.utc),
}

_DETAIL_ROW = {**_SAMPLE_ROW, "metrics_snapshot": {"nav": 1_000_000}}


def _make_client(list_return=None, get_return=None):
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_validation_repo

    app = create_app()
    mock_repo = MagicMock()
    mock_repo.list_validations.return_value = list_return if list_return is not None else []
    mock_repo.get_by_correlation_id.return_value = get_return

    app.dependency_overrides[get_validation_repo] = lambda: mock_repo
    return TestClient(app), mock_repo


# ── GET /trades/validations ───────────────────────────────────────────────────

class TestListValidations:

    def test_returns_200(self):
        client, _ = _make_client()
        assert client.get("/trades/validations").status_code == 200

    def test_returns_items_and_count(self):
        client, _ = _make_client(list_return=[_SAMPLE_ROW])
        data = client.get("/trades/validations").json()
        assert "items" in data
        assert "count" in data
        assert data["count"] == 1
        assert len(data["items"]) == 1

    def test_empty_db_returns_zero_count(self):
        client, _ = _make_client(list_return=[])
        data = client.get("/trades/validations").json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_approved_filter_true_forwarded_to_repo(self):
        client, mock_repo = _make_client()
        client.get("/trades/validations?approved=true")
        mock_repo.list_validations.assert_called_once_with(approved=True, days=7, limit=50)

    def test_approved_filter_false_forwarded_to_repo(self):
        client, mock_repo = _make_client()
        client.get("/trades/validations?approved=false")
        mock_repo.list_validations.assert_called_once_with(approved=False, days=7, limit=50)

    def test_days_and_limit_params_forwarded(self):
        client, mock_repo = _make_client()
        client.get("/trades/validations?days=14&limit=100")
        mock_repo.list_validations.assert_called_once_with(approved=None, days=14, limit=100)

    def test_default_params_forwarded(self):
        client, mock_repo = _make_client()
        client.get("/trades/validations")
        mock_repo.list_validations.assert_called_once_with(approved=None, days=7, limit=50)

    def test_item_has_correlation_id_as_string(self):
        client, _ = _make_client(list_return=[_SAMPLE_ROW])
        data = client.get("/trades/validations").json()
        assert isinstance(data["items"][0]["correlation_id"], str)


# ── GET /trades/validations/{correlation_id} ──────────────────────────────────

class TestGetValidation:

    def test_returns_200_when_found(self):
        client, _ = _make_client(get_return=_DETAIL_ROW)
        assert client.get(f"/trades/validations/{_VALID_UUID}").status_code == 200

    def test_has_metrics_snapshot(self):
        client, _ = _make_client(get_return=_DETAIL_ROW)
        data = client.get(f"/trades/validations/{_VALID_UUID}").json()
        assert data["metrics_snapshot"] == {"nav": 1_000_000}

    def test_returns_404_for_invalid_uuid_format(self):
        # Invalid UUID format maps to 404 (not 422) — "malformed ID" is
        # semantically equivalent to "resource not found" from client perspective.
        client, _ = _make_client(get_return=None)
        assert client.get("/trades/validations/not-a-uuid").status_code == 404

    def test_returns_404_when_valid_uuid_not_in_db(self):
        client, _ = _make_client(get_return=None)
        assert client.get(f"/trades/validations/{_VALID_UUID}").status_code == 404
