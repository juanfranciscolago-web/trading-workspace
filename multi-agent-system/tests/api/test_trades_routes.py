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

# ── Fixtures: Critiques / Decisions / Atlas Validations (Sprint 4 B.4.6) ──────

def _make_critique(corr_id: str = _VALID_PROPOSAL_UUID) -> "CritiqueMessage":
    """Build a valid CritiqueMessage for use as a mock return value."""
    from multi_agent.communication.schemas import CritiqueArgument, CritiqueMessage
    from multi_agent.communication.enums import AgentId, Stance
    return CritiqueMessage(
        correlation_id=UUID(corr_id),
        agent_id=AgentId.APOLLO,
        stance=Stance.AGREE,
        argument=CritiqueArgument(
            summary="macro tailwind",
            concern="watch FOMC",
            data_that_would_change_my_mind="VIX > 25",
        ),
        veto_request=False,
        contrarian_flag_raised=False,
    )


def _make_decision(corr_id: str = _VALID_PROPOSAL_UUID) -> "DecisionMessage":
    """Build a valid DecisionMessage for use as a mock return value."""
    from multi_agent.communication.schemas import ConsensusState, DecisionMessage
    from multi_agent.communication.enums import AgentId, ConsensusType, DecisionOutcome
    return DecisionMessage(
        correlation_id=UUID(corr_id),
        agent_id=AgentId.ATLAS,
        outcome=DecisionOutcome.APPROVED,
        consensus_state=ConsensusState(
            agree=[AgentId.APOLLO],
            consensus_type=ConsensusType.UNANIMOUS,
        ),
    )


def _make_atlas_validation(corr_id: str = _VALID_PROPOSAL_UUID) -> "AtlasValidationMessage":
    """Build a valid AtlasValidationMessage for use as a mock return value."""
    from decimal import Decimal
    from multi_agent.communication.schemas import AtlasValidationMessage
    from multi_agent.communication.enums import AgentId, RiskMode
    return AtlasValidationMessage(
        correlation_id=UUID(corr_id),
        agent_id=AgentId.ATLAS,
        atlas_version="atlas-1.0",
        approved=True,
        executed_size=Decimal("2.5"),
        original_size=Decimal("2.5"),
        reason="approved",
        risk_mode=RiskMode.GREEN,
        portfolio_snapshot_id="a" * 64,
        evaluation_time_ms=1.5,
    )


def _make_pipeline_client(
    *,
    proposal_row=None,
    critiques=None,
    decision=None,
    atlas_validation=None,
):
    """Build a TestClient with the 4 pipeline-relevant repo methods mocked."""
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_message_repo

    app = create_app()
    mock_repo = MagicMock()
    mock_repo.get_proposal_by_correlation_id.return_value = proposal_row
    mock_repo.list_critiques_by_correlation_id.return_value = critiques or []
    mock_repo.get_decision_by_correlation_id.return_value = decision
    mock_repo.get_atlas_validation_by_correlation_id.return_value = atlas_validation

    app.dependency_overrides[get_message_repo] = lambda: mock_repo
    return TestClient(app), mock_repo


# ── GET /trades/critiques/{correlation_id} ────────────────────────────────────

class TestListCritiques:

    def test_list_critiques_returns_200_with_items_when_found(self):
        critique = _make_critique()
        client, _ = _make_pipeline_client(critiques=[critique])
        r = client.get(f"/trades/critiques/{_VALID_PROPOSAL_UUID}")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["stance"] == "AGREE"

    def test_list_critiques_returns_200_empty_when_no_critiques(self):
        client, _ = _make_pipeline_client(critiques=[])
        r = client.get(f"/trades/critiques/{_VALID_PROPOSAL_UUID}")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_list_critiques_returns_404_on_malformed_uuid(self):
        client, _ = _make_pipeline_client()
        r = client.get("/trades/critiques/not-a-uuid")
        assert r.status_code == 404

    def test_list_critiques_count_matches_items_length(self):
        critiques = [_make_critique(), _make_critique()]
        client, _ = _make_pipeline_client(critiques=critiques)
        data = client.get(f"/trades/critiques/{_VALID_PROPOSAL_UUID}").json()
        assert data["count"] == len(data["items"])
        assert data["count"] == 2


# ── GET /trades/decisions/{correlation_id} ────────────────────────────────────

class TestGetDecision:

    def test_get_decision_returns_200_with_decision_when_found(self):
        decision = _make_decision()
        client, _ = _make_pipeline_client(decision=decision)
        r = client.get(f"/trades/decisions/{_VALID_PROPOSAL_UUID}")
        assert r.status_code == 200
        data = r.json()
        assert data["outcome"] == "APPROVED"
        assert data["consensus_state"]["consensus_type"] == "UNANIMOUS"

    def test_get_decision_returns_404_when_no_decision(self):
        client, _ = _make_pipeline_client(decision=None)
        r = client.get(f"/trades/decisions/{_VALID_PROPOSAL_UUID}")
        assert r.status_code == 404
        assert r.json()["detail"] == "decision not found"

    def test_get_decision_returns_404_on_malformed_uuid(self):
        client, _ = _make_pipeline_client()
        r = client.get("/trades/decisions/not-a-uuid")
        assert r.status_code == 404
        assert r.json()["detail"] == "decision not found"


# ── GET /trades/pipeline/{correlation_id} ─────────────────────────────────────

class TestGetPipeline:

    def test_get_pipeline_returns_200_with_full_state_when_complete(self):
        proposal_row = {**_PROPOSAL_DETAIL_ROW, "status": "atlas_validated"}
        client, _ = _make_pipeline_client(
            proposal_row=proposal_row,
            critiques=[_make_critique()],
            decision=_make_decision(),
            atlas_validation=_make_atlas_validation(),
        )
        r = client.get(f"/trades/pipeline/{_VALID_PROPOSAL_UUID}")
        assert r.status_code == 200
        data = r.json()
        assert data["proposal"]["trade"]["ticker"] == "SPY"
        assert len(data["critiques"]) == 1
        assert data["decision"]["outcome"] == "APPROVED"
        assert data["atlas_validation"]["approved"] is True

    def test_get_pipeline_returns_404_when_proposal_not_found(self):
        client, _ = _make_pipeline_client(proposal_row=None)
        r = client.get(f"/trades/pipeline/{_VALID_PROPOSAL_UUID}")
        assert r.status_code == 404
        assert r.json()["detail"] == "proposal not found"

    def test_get_pipeline_returns_404_on_malformed_uuid(self):
        client, _ = _make_pipeline_client()
        r = client.get("/trades/pipeline/not-a-uuid")
        assert r.status_code == 404
        assert r.json()["detail"] == "proposal not found"

    def test_get_pipeline_returns_partial_state_when_chain_in_flight(self):
        """Mid-pipeline: proposal exists, no critiques yet, no decision, no atlas."""
        proposal_row = {**_PROPOSAL_DETAIL_ROW, "status": "pending"}
        client, _ = _make_pipeline_client(
            proposal_row=proposal_row,
            critiques=[],
            decision=None,
            atlas_validation=None,
        )
        r = client.get(f"/trades/pipeline/{_VALID_PROPOSAL_UUID}")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "pending"
        assert data["critiques"] == []
        assert data["decision"] is None
        assert data["atlas_validation"] is None

    def test_get_pipeline_status_field_from_proposals_row(self):
        """Status field comes directly from the proposals row's status column,
        not inferred from the presence/absence of other pipeline messages."""
        proposal_row = {**_PROPOSAL_DETAIL_ROW, "status": "under_critique"}
        client, _ = _make_pipeline_client(
            proposal_row=proposal_row,
            critiques=[],
            decision=None,
            atlas_validation=None,
        )
        r = client.get(f"/trades/pipeline/{_VALID_PROPOSAL_UUID}")
        data = r.json()
        assert data["status"] == "under_critique"
