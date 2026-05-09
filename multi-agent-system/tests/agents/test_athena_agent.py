"""
Unit tests for AthenaAgent (Sprint 3 B.3.4).

No real LLM, no real data layer, no DB. ClaudeRouter is mocked via a helper
that returns a configurable response.text. DataLayer is a MagicMock with
snapshot() returning a stub MarketState.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from claude_router.router import Criticality

from multi_agent.agents.athena_agent import AthenaAgent
from multi_agent.agents.athena_prompt import SYSTEM_PROMPT
from multi_agent.communication.enums import AgentId
from multi_agent.communication.schemas import ProposalMessage


# ── Shape A — valid LLM output (hardcoded module-level for explicitness) ──────

_SHAPE_A_JSON = json.dumps({
    "trade": {
        "ticker": "SPY",
        "asset_class": "option",
        "strategy_type": "CSP",
        "structure": {
            "legs": [
                {
                    "action": "sell",
                    "instrument_type": "put",
                    "strike": "425.0",
                    "expiration": "2026-06-15",
                    "quantity": 1,
                },
            ],
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_router_with_response(text: str) -> MagicMock:
    """Build a ClaudeRouter mock returning a ClaudeResponse-like with given text."""
    router = MagicMock()
    response = MagicMock()
    response.text = text
    response.model_used = "claude-sonnet-4-6"
    response.request_id = "test-req-123"
    response.cost = MagicMock(total_usd=0.001)
    router.send.return_value = response
    return router


_FIXED_TIMESTAMP = datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)


def _make_data_layer(timestamp: datetime = _FIXED_TIMESTAMP) -> MagicMock:
    """Build a DataLayer mock returning a stub MarketState with the given timestamp."""
    layer = MagicMock()
    state = MagicMock()
    state.timestamp = timestamp
    state.tickers = {}
    state.correlations = {}
    state.to_dict.return_value = {
        "timestamp": timestamp.isoformat(),
        "tickers": {},
        "correlations": {},
    }
    layer.snapshot.return_value = state
    return layer


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAthenaAgent:

    def test_agent_id_is_athena(self):
        assert AthenaAgent.agent_id == AgentId.ATHENA

    def test_constructor_stores_dependencies(self):
        router = MagicMock()
        layer = MagicMock()
        agent = AthenaAgent(router, layer)
        assert agent._claude_router is router
        assert agent._data_layer is layer

    def test_generate_proposal_calls_router_with_correct_params(self):
        router = _make_router_with_response(_SHAPE_A_JSON)
        layer = _make_data_layer()
        agent = AthenaAgent(router, layer)
        agent.generate_proposal(uuid4())

        router.send.assert_called_once()
        kwargs = router.send.call_args.kwargs
        assert kwargs["task_type"] == "proposal_generation"
        assert kwargs["system_prompt"] == SYSTEM_PROMPT
        assert kwargs["agent"] == "athena"
        assert kwargs["criticality"] == Criticality.STANDARD
        # user prompt should embed the snapshot keys
        assert "tickers" in kwargs["user_prompt"]

    def test_generate_proposal_returns_proposal_for_shape_a(self):
        router = _make_router_with_response(_SHAPE_A_JSON)
        layer = _make_data_layer()
        agent = AthenaAgent(router, layer)
        result = agent.generate_proposal(uuid4())
        assert isinstance(result, ProposalMessage)
        assert result.trade.ticker == "SPY"
        assert result.conviction_score == 72

    def test_generate_proposal_returns_none_for_shape_b(self):
        router = _make_router_with_response(_SHAPE_B_JSON)
        layer = _make_data_layer()
        agent = AthenaAgent(router, layer)
        result = agent.generate_proposal(uuid4())
        assert result is None

    def test_correlation_id_propagated(self):
        router = _make_router_with_response(_SHAPE_A_JSON)
        layer = _make_data_layer()
        agent = AthenaAgent(router, layer)
        corr = uuid4()
        result = agent.generate_proposal(corr)
        assert result is not None
        assert result.correlation_id == corr

    def test_agent_id_set_in_proposal(self):
        router = _make_router_with_response(_SHAPE_A_JSON)
        layer = _make_data_layer()
        agent = AthenaAgent(router, layer)
        result = agent.generate_proposal(uuid4())
        assert result is not None
        assert result.agent_id == AgentId.ATHENA

    def test_data_signature_populated(self):
        router = _make_router_with_response(_SHAPE_A_JSON)
        layer = _make_data_layer()
        agent = AthenaAgent(router, layer)
        result = agent.generate_proposal(uuid4())
        assert result is not None
        assert result.data_signature.data_timestamp == _FIXED_TIMESTAMP
        assert result.data_signature.model_version == "athena-real-v1.0"
        assert "stub_data_layer" in result.data_signature.data_sources

    def test_invalid_json_raises(self):
        router = _make_router_with_response("not json at all")
        layer = _make_data_layer()
        agent = AthenaAgent(router, layer)
        with pytest.raises(json.JSONDecodeError):
            agent.generate_proposal(uuid4())

    def test_invalid_shape_raises(self):
        """LLM produces Shape A but with nested fields missing → Pydantic raises."""
        invalid_shape = json.dumps({
            "trade": {"ticker": "SPY"},  # missing asset_class, strategy_type, structure
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
        })
        router = _make_router_with_response(invalid_shape)
        layer = _make_data_layer()
        agent = AthenaAgent(router, layer)
        with pytest.raises(ValidationError):
            agent.generate_proposal(uuid4())

    def test_missing_top_level_key_raises_key_error(self):
        """LLM produces Shape A but missing a top-level required key → KeyError."""
        # Has thesis/conviction/sizing but missing 'trade' top-level key
        invalid = json.dumps({
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
        })
        router = _make_router_with_response(invalid)
        layer = _make_data_layer()
        agent = AthenaAgent(router, layer)
        with pytest.raises(KeyError):
            agent.generate_proposal(uuid4())
