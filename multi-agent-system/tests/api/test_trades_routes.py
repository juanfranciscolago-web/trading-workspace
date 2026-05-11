"""
Unit tests for trades API routes.
No DB — ValidationRepository is mocked via FastAPI dependency overrides.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID

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


# ── Fixtures: Proposals ───────────────────────────────────────────────────────

_VALID_PROPOSAL_UUID = "fedcba98-7654-3210-fedc-ba9876543210"

# psycopg3 returns UUID column values as UUID objects, not strings.
# Mirror that here so _row_to_proposal_summary's str() conversion is
# actually exercised by test_item_has_correlation_id_as_string.
_PROPOSAL_SUMMARY_ROW = {
    "correlation_id": UUID(_VALID_PROPOSAL_UUID),
    "proposing_agent": "athena",
    "ticker": "SPY",
    "asset_class": "option",
    "strategy_type": "CSP",
    "conviction_score": 72,
    "proposed_size_pct": 2.5,
    "proposed_size_usd": 25000.0,
    "time_horizon_days": 30,
    "status": "pending",
    "created_at": datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc),
}


def _build_proposal_payload(corr_id: str) -> dict:
    """Build a valid ProposalMessage's JSON-mode dict (matches what JSONB stores)."""
    from multi_agent.communication.schemas import ProposalMessage
    payload = {
        "message_type": "PROPOSAL",
        "correlation_id": corr_id,
        "agent_id": "ATHENA",
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
            "premise": "x",
            "mechanism": "x",
            "key_data_points": ["x"],
            "invalidation": "x",
            "target": "x",
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
        "self_acknowledged_biases": [],
        "data_signature": {
            "data_timestamp": "2026-05-11T12:00:00+00:00",
            "data_sources": ["stub_data_layer"],
            "model_version": "athena-real-v1.0",
        },
    }
    msg = ProposalMessage.model_validate(payload)
    return msg.model_dump(mode="json")


_PROPOSAL_DETAIL_ROW = {
    **_PROPOSAL_SUMMARY_ROW,
    "full_payload": _build_proposal_payload(_VALID_PROPOSAL_UUID),
}


def _make_proposals_client(list_return=None, get_return=None):
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_message_repo

    app = create_app()
    mock_repo = MagicMock()
    mock_repo.list_proposals.return_value = list_return if list_return is not None else []
    mock_repo.get_proposal_by_correlation_id.return_value = get_return

    app.dependency_overrides[get_message_repo] = lambda: mock_repo
    return TestClient(app), mock_repo


# ── GET /trades/proposals ──────────────────────────────────────────────────────

class TestListProposals:

    def test_returns_200(self):
        client, _ = _make_proposals_client()
        assert client.get("/trades/proposals").status_code == 200

    def test_returns_items_and_count(self):
        client, _ = _make_proposals_client(list_return=[_PROPOSAL_SUMMARY_ROW])
        data = client.get("/trades/proposals").json()
        assert data["count"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["ticker"] == "SPY"
        assert data["items"][0]["proposing_agent"] == "athena"

    def test_empty_returns_zero_count(self):
        client, _ = _make_proposals_client(list_return=[])
        data = client.get("/trades/proposals").json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_agent_id_filter_forwarded(self):
        client, mock_repo = _make_proposals_client(list_return=[])
        client.get("/trades/proposals?agent_id=athena")
        mock_repo.list_proposals.assert_called_once_with(
            days=7, limit=50, agent_id="athena"
        )

    def test_days_and_limit_params_forwarded(self):
        client, mock_repo = _make_proposals_client(list_return=[])
        client.get("/trades/proposals?days=14&limit=10")
        mock_repo.list_proposals.assert_called_once_with(
            days=14, limit=10, agent_id=None
        )

    def test_default_params_forwarded(self):
        client, mock_repo = _make_proposals_client(list_return=[])
        client.get("/trades/proposals")
        mock_repo.list_proposals.assert_called_once_with(
            days=7, limit=50, agent_id=None
        )

    def test_item_has_correlation_id_as_string(self):
        client, _ = _make_proposals_client(list_return=[_PROPOSAL_SUMMARY_ROW])
        data = client.get("/trades/proposals").json()
        assert data["items"][0]["correlation_id"] == _VALID_PROPOSAL_UUID
        assert isinstance(data["items"][0]["correlation_id"], str)


# ── GET /trades/proposals/{correlation_id} ─────────────────────────────────────

class TestGetProposal:

    def test_returns_200_when_found(self):
        client, _ = _make_proposals_client(get_return=_PROPOSAL_DETAIL_ROW)
        r = client.get(f"/trades/proposals/{_VALID_PROPOSAL_UUID}")
        assert r.status_code == 200

    def test_returns_full_proposal_payload(self):
        """Detail endpoint reconstructs ProposalMessage from JSONB full_payload."""
        client, _ = _make_proposals_client(get_return=_PROPOSAL_DETAIL_ROW)
        data = client.get(f"/trades/proposals/{_VALID_PROPOSAL_UUID}").json()
        assert data["trade"]["ticker"] == "SPY"
        assert data["conviction_score"] == 72
        assert data["agent_id"] == "ATHENA"
        assert data["correlation_id"] == _VALID_PROPOSAL_UUID

    def test_returns_404_for_invalid_uuid_format(self):
        client, _ = _make_proposals_client()
        r = client.get("/trades/proposals/not-a-uuid")
        assert r.status_code == 404
        assert r.json()["detail"] == "proposal not found"

    def test_returns_404_when_valid_uuid_not_in_db(self):
        client, _ = _make_proposals_client(get_return=None)
        r = client.get(f"/trades/proposals/{_VALID_PROPOSAL_UUID}")
        assert r.status_code == 404
        assert r.json()["detail"] == "proposal not found"
