"""
Unit tests for ApolloAgent (Sprint 4 B.4.2).

No real LLM, no real DB. ClaudeRouter is mocked. market_state comes from
the real StubDataLayer (no I/O — it's a pure-Python stub). A canonical
ProposalMessage fixture provides the input to critique_proposal.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from multi_agent.agents.apollo_agent import ApolloAgent
from multi_agent.communication.enums import (
    AgentId,
    AssetClass,
    Direction,
    OptionType,
    Stance,
    StrategyType,
)
from multi_agent.communication.schemas import (
    CritiqueMessage,
    DataSignature,
    OptionLeg,
    ProposalMessage,
    Thesis,
    TradeDetails,
    TradeSizing,
    TradeStructure,
)
from multi_agent.data_layer import StubDataLayer


# ── Module-level constants and fixtures ───────────────────────────────────────

_FIXED_TIMESTAMP = datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)
_FIXED_CORR_ID = UUID("11111111-1111-4111-8111-111111111111")
_FIXED_PROPOSAL_MSG_ID = UUID("22222222-2222-4222-8222-222222222222")


_SHAPE_A_JSON = json.dumps({
    "stance": "DISAGREE",
    "argument": {
        "summary": "Macro regime shift undermines the statistical pattern cited",
        "evidence": [
            {
                "claim": "Fed pivot pricing flipping after CPI surprise",
                "data_source": "fed_funds_futures",
                "value": "0.65",
            },
            {
                "claim": "Credit spreads widening signals risk-off rotation",
                "data_source": "bloomberg_hy_oas",
                "value": "+45bps",
            },
        ],
        "concern": "IV crush thesis assumes regime continuity that data is starting to invalidate",
        "data_that_would_change_my_mind": "HY OAS stabilizes and Fed pivot pricing reverts",
    },
    "veto_request": False,
    "contrarian_flag_raised": True,
    "alternative_proposal": None,
})


def _make_router_with_response(text: str) -> MagicMock:
    """Build a ClaudeRouter mock returning a ClaudeResponse-like with given text."""
    router = MagicMock()
    response = MagicMock()
    response.text = text
    response.model_used = "claude-sonnet-4-6"
    response.request_id = "test-req-456"
    response.cost = MagicMock(total_usd=0.001)
    router.send.return_value = response
    return router


def _make_proposal(message_id: UUID = _FIXED_PROPOSAL_MSG_ID) -> ProposalMessage:
    """Canonical ATHENA-style ProposalMessage for critique input."""
    return ProposalMessage(
        message_id=message_id,
        agent_id=AgentId.ATHENA,
        trade=TradeDetails(
            ticker="MSFT",
            asset_class=AssetClass.OPTION,
            strategy_type=StrategyType.CSP,
            structure=TradeStructure(
                legs=[OptionLeg(
                    action=Direction.SELL,
                    instrument_type=OptionType.PUT,
                    strike=Decimal("410.00"),
                    expiration=date(2026, 6, 19),
                    quantity=10,
                )],
                buying_power_required=Decimal("41000.00"),
            ),
        ),
        thesis=Thesis(
            premise="MSFT en soporte con IV Rank elevado",
            mechanism="IV crush + soporte horizontal",
            key_data_points=["IV Rank: 62"],
            invalidation="Cierre debajo de 405",
            target="50% max profit",
            time_horizon_days=45,
            expected_holding_period_days=22,
        ),
        conviction_score=78,
        sizing=TradeSizing(
            proposed_size_pct_portfolio=4.0,
            proposed_size_usd=Decimal("40000.00"),
            kelly_suggested=5.0,
            kelly_fraction_applied=0.25,
        ),
        data_signature=DataSignature(
            data_sources=["test"],
            data_timestamp=_FIXED_TIMESTAMP,
            model_version="test-v1",
        ),
    )


@pytest.fixture
def market_state():
    """Real StubDataLayer snapshot — no mocking needed for pure-Python stub."""
    return StubDataLayer().snapshot()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestApolloAgentCritique:

    def test_critique_proposal_parses_shape_a_correctly(self, market_state):
        router = _make_router_with_response(_SHAPE_A_JSON)
        agent = ApolloAgent(router)
        result = agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)
        assert isinstance(result, CritiqueMessage)
        assert result.stance == Stance.DISAGREE
        assert len(result.argument.evidence) == 2
        assert result.argument.evidence[0].data_source == "fed_funds_futures"
        assert result.argument.concern.startswith("IV crush")

    def test_critique_proposal_injects_agent_id_apollo(self, market_state):
        router = _make_router_with_response(_SHAPE_A_JSON)
        agent = ApolloAgent(router)
        result = agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)
        assert result.agent_id == AgentId.APOLLO

    def test_critique_proposal_sets_correlation_id_from_caller(self, market_state):
        router = _make_router_with_response(_SHAPE_A_JSON)
        agent = ApolloAgent(router)
        corr = uuid4()
        result = agent.critique_proposal(_make_proposal(), market_state, corr)
        assert result.correlation_id == corr

    def test_critique_proposal_sets_parent_message_id_to_proposal_id(self, market_state):
        router = _make_router_with_response(_SHAPE_A_JSON)
        agent = ApolloAgent(router)
        proposal_id = uuid4()
        proposal = _make_proposal(message_id=proposal_id)
        result = agent.critique_proposal(proposal, market_state, _FIXED_CORR_ID)
        assert result.parent_message_id == proposal_id

    def test_critique_proposal_handles_veto_request_true(self, market_state):
        shape = json.loads(_SHAPE_A_JSON)
        shape["veto_request"] = True
        router = _make_router_with_response(json.dumps(shape))
        agent = ApolloAgent(router)
        result = agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)
        assert result.veto_request is True

    def test_critique_proposal_handles_contrarian_flag_true(self, market_state):
        # _SHAPE_A_JSON already has contrarian_flag_raised=True
        router = _make_router_with_response(_SHAPE_A_JSON)
        agent = ApolloAgent(router)
        result = agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)
        assert result.contrarian_flag_raised is True

    def test_critique_proposal_defaults_veto_to_false_when_absent(self, market_state):
        shape = json.loads(_SHAPE_A_JSON)
        del shape["veto_request"]
        router = _make_router_with_response(json.dumps(shape))
        agent = ApolloAgent(router)
        result = agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)
        assert result.veto_request is False

    def test_critique_proposal_defaults_contrarian_to_false_when_absent(self, market_state):
        shape = json.loads(_SHAPE_A_JSON)
        del shape["contrarian_flag_raised"]
        router = _make_router_with_response(json.dumps(shape))
        agent = ApolloAgent(router)
        result = agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)
        assert result.contrarian_flag_raised is False

    def test_critique_proposal_accepts_neutral_stance(self, market_state):
        shape = json.loads(_SHAPE_A_JSON)
        shape["stance"] = "NEUTRAL"
        router = _make_router_with_response(json.dumps(shape))
        agent = ApolloAgent(router)
        result = agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)
        assert result.stance == Stance.NEUTRAL

    def test_critique_proposal_raises_on_invalid_json(self, market_state):
        router = _make_router_with_response("not json at all")
        agent = ApolloAgent(router)
        with pytest.raises(json.JSONDecodeError):
            agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)

    def test_critique_proposal_raises_on_missing_required_field(self, market_state):
        """LLM produces a shape missing the 'stance' top-level key → KeyError."""
        shape = json.loads(_SHAPE_A_JSON)
        del shape["stance"]
        router = _make_router_with_response(json.dumps(shape))
        agent = ApolloAgent(router)
        with pytest.raises(KeyError):
            agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)

    def test_critique_proposal_invokes_router_with_correct_params(self, market_state):
        """Regression guard: APOLLO must call ClaudeRouter with the right
        task_type, agent name, and criticality. A silent change here
        (e.g. task_type set to a different routing rule) would break
        cost tracking and routing without other tests noticing."""
        from claude_router.router import Criticality

        router = _make_router_with_response(_SHAPE_A_JSON)
        agent = ApolloAgent(router)
        agent.critique_proposal(_make_proposal(), market_state, _FIXED_CORR_ID)

        assert router.send.called
        kwargs = router.send.call_args.kwargs
        assert kwargs["task_type"] == "cross_examination"
        assert kwargs["agent"] == "apollo"
        assert kwargs["criticality"] == Criticality.STANDARD


class TestApolloAgentGenerateProposal:

    def test_generate_proposal_raises_not_implemented(self):
        """Sprint 4 stub: APOLLO does not generate proposals (D7.2)."""
        agent = ApolloAgent(MagicMock())
        with pytest.raises(NotImplementedError, match="critique-only"):
            agent.generate_proposal(uuid4())
