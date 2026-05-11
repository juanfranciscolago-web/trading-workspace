"""
Unit tests for the consensus engine.

Each test runs a full cycle through the orchestrator and checks that
the consensus outcome and size modulation match the scenario contract.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from multi_agent.agents import SCENARIOS, build_orchestrator
from multi_agent.agents.consensus import evaluate
from multi_agent.communication.enums import (
    AgentId,
    AssetClass,
    AtlasDecision,
    ConsensusType,
    DecisionOutcome,
    Direction,
    OptionType,
    Stance,
    StrategyType,
)
from multi_agent.communication.schemas import (
    CritiqueArgument,
    CritiqueMessage,
    DataSignature,
    OptionLeg,
    ProposalMessage,
    Thesis,
    TradeDetails,
    TradeSizing,
    TradeStructure,
)

from .conftest import CapturingRepository


def _run(scenario_name: str):
    repo = CapturingRepository()
    orc = build_orchestrator(repo)
    scenario = SCENARIOS[scenario_name]
    return orc.run_cycle(scenario), repo


class TestAllAgree:
    def test_outcome_is_approved(self):
        result, _ = _run("all_agree")
        assert result.decision.outcome == DecisionOutcome.APPROVED

    def test_consensus_type_unanimous(self):
        result, _ = _run("all_agree")
        assert result.decision.consensus_state.consensus_type == ConsensusType.UNANIMOUS

    def test_no_size_modulation(self):
        result, _ = _run("all_agree")
        assert result.decision.size_modulation is None

    def test_all_four_critics_in_agree_list(self):
        result, _ = _run("all_agree")
        cs = result.decision.consensus_state
        assert len(cs.agree) == 4
        assert len(cs.disagree) == 0

    def test_atlas_approves(self):
        result, _ = _run("all_agree")
        assert result.atlas_validation.approved is True


class TestNyxDissents:
    def test_outcome_is_approved_with_conditions(self):
        result, _ = _run("nyx_dissents")
        assert result.decision.outcome == DecisionOutcome.APPROVED_WITH_CONDITIONS

    def test_consensus_type_productive_disagreement(self):
        result, _ = _run("nyx_dissents")
        assert (
            result.decision.consensus_state.consensus_type
            == ConsensusType.MAJORITY_WITH_PRODUCTIVE_DISAGREEMENT
        )

    def test_size_reduced_to_50pct(self):
        result, _ = _run("nyx_dissents")
        sm = result.decision.size_modulation
        assert sm is not None
        scenario = SCENARIOS["nyx_dissents"]
        assert sm.approved_size_pct == pytest.approx(scenario.proposed_size_pct * 0.5, rel=1e-3)

    def test_nyx_in_disagree_list(self):
        result, _ = _run("nyx_dissents")
        from multi_agent.communication.enums import AgentId
        assert AgentId.NYX in result.decision.consensus_state.disagree

    def test_nyx_contrarian_flag_raised(self):
        result, _ = _run("nyx_dissents")
        nyx_critique = next(c for c in result.critiques if c.agent_id.value == "NYX")
        assert nyx_critique.contrarian_flag_raised is True


class TestDeepDisagreement:
    def test_outcome_is_rejected(self):
        result, _ = _run("deep_disagreement")
        assert result.decision.outcome == DecisionOutcome.REJECTED

    def test_consensus_type_split(self):
        result, _ = _run("deep_disagreement")
        assert result.decision.consensus_state.consensus_type == ConsensusType.SPLIT

    def test_two_agree_two_disagree(self):
        result, _ = _run("deep_disagreement")
        cs = result.decision.consensus_state
        assert len(cs.agree) == 2
        assert len(cs.disagree) == 2

    def test_atlas_not_called_on_rejected(self):
        # ATLAS still validates (for audit) even on REJECTED — but decision is BLOCKED only
        # if the consensus itself passed. Here we just verify the atlas validation exists.
        result, repo = _run("deep_disagreement")
        assert len(repo.atlas_validations) == 1


class TestAtlasBlocks:
    def test_consensus_outcome_unanimous(self):
        result, _ = _run("atlas_blocks")
        assert result.decision.outcome == DecisionOutcome.APPROVED

    def test_atlas_blocks(self):
        result, _ = _run("atlas_blocks")
        assert result.atlas_validation.approved is False

    def test_block_reason_contains_atlas_reason(self):
        result, _ = _run("atlas_blocks")
        scenario = SCENARIOS["atlas_blocks"]
        assert scenario.atlas_block_reason in result.atlas_validation.reason

    def test_risk_mode_black_when_blocked(self):
        result, _ = _run("atlas_blocks")
        from multi_agent.communication.enums import RiskMode
        assert result.atlas_validation.risk_mode == RiskMode.BLACK


class TestHighConvictionSolo:
    def test_outcome_approved_with_conditions(self):
        result, _ = _run("high_conviction_solo")
        assert result.decision.outcome == DecisionOutcome.APPROVED_WITH_CONDITIONS

    def test_consensus_type_no_quorum(self):
        result, _ = _run("high_conviction_solo")
        assert result.decision.consensus_state.consensus_type == ConsensusType.NO_QUORUM

    def test_size_reduced_to_33pct(self):
        result, _ = _run("high_conviction_solo")
        sm = result.decision.size_modulation
        assert sm is not None
        scenario = SCENARIOS["high_conviction_solo"]
        assert sm.approved_size_pct == pytest.approx(scenario.proposed_size_pct * 0.33, rel=1e-2)

    def test_all_critics_neutral(self):
        result, _ = _run("high_conviction_solo")
        cs = result.decision.consensus_state
        assert len(cs.neutral) == 4
        assert len(cs.agree) == 0
        assert len(cs.disagree) == 0

    def test_conviction_score_is_90_plus(self):
        result, _ = _run("high_conviction_solo")
        assert result.proposal.conviction_score >= 90


# ─────────────────────────────────────────────────────────────────────────────
# Unit-level engine fixtures
# Direct calls to evaluate() with handcrafted inputs exercise paths
# (veto, contrarian propagation) not covered by scenario-driven cycles above.
# ─────────────────────────────────────────────────────────────────────────────

def _make_proposal(correlation_id) -> ProposalMessage:
    return ProposalMessage(
        agent_id=AgentId.ATHENA,
        correlation_id=correlation_id,
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
            data_timestamp=datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc),
            model_version="test-v1",
        ),
    )


def _make_critique(
    correlation_id,
    agent_id: AgentId,
    stance: Stance = Stance.AGREE,
    veto: bool = False,
    contrarian: bool = False,
) -> CritiqueMessage:
    return CritiqueMessage(
        agent_id=agent_id,
        correlation_id=correlation_id,
        stance=stance,
        argument=CritiqueArgument(
            summary=f"{agent_id.value} take",
            concern="test concern",
            data_that_would_change_my_mind="test signal",
        ),
        veto_request=veto,
        contrarian_flag_raised=contrarian,
    )


class TestVetoRequest:
    def test_single_veto_rejects(self):
        corr = uuid4()
        proposal = _make_proposal(corr)
        critiques = [
            _make_critique(corr, AgentId.NYX, stance=Stance.DISAGREE, veto=True),
        ]
        decision = evaluate(proposal, critiques, corr)
        assert decision.outcome == DecisionOutcome.REJECTED
        assert decision.consensus_state.consensus_type == ConsensusType.VETOED
        assert decision.conditions == ["vetoed_by:NYX"]
        assert decision.size_modulation is None

    def test_multiple_vetos_lists_all(self):
        corr = uuid4()
        proposal = _make_proposal(corr)
        critiques = [
            _make_critique(corr, AgentId.NYX, stance=Stance.DISAGREE, veto=True),
            _make_critique(corr, AgentId.APOLLO, stance=Stance.DISAGREE, veto=True),
        ]
        decision = evaluate(proposal, critiques, corr)
        assert decision.outcome == DecisionOutcome.REJECTED
        assert decision.consensus_state.consensus_type == ConsensusType.VETOED
        assert decision.conditions == ["vetoed_by:NYX", "vetoed_by:APOLLO"]
        assert decision.size_modulation is None

    def test_veto_overrides_majority_agree(self):
        # 3 AGREE + 1 DISAGREE+veto. Without veto, branch 4 (MAJORITY plain
        # dissent) would APPROVE full size. Veto must win.
        corr = uuid4()
        proposal = _make_proposal(corr)
        critiques = [
            _make_critique(corr, AgentId.APOLLO, stance=Stance.AGREE),
            _make_critique(corr, AgentId.HERMES, stance=Stance.AGREE),
            _make_critique(corr, AgentId.VESTA, stance=Stance.AGREE),
            _make_critique(corr, AgentId.NYX, stance=Stance.DISAGREE, veto=True),
        ]
        decision = evaluate(proposal, critiques, corr)
        assert decision.outcome == DecisionOutcome.REJECTED
        assert decision.consensus_state.consensus_type == ConsensusType.VETOED
        assert "vetoed_by:NYX" in decision.conditions
        # consensus_state still tracks full vote tally for audit even when veto overrides
        assert len(decision.consensus_state.agree) == 3
        assert len(decision.consensus_state.disagree) == 1


class TestContrarianFlagPropagation:
    def test_contrarian_flag_propagates_when_raised(self):
        corr = uuid4()
        proposal = _make_proposal(corr)
        critiques = [
            _make_critique(corr, AgentId.APOLLO, stance=Stance.AGREE),
            _make_critique(corr, AgentId.HERMES, stance=Stance.AGREE),
            _make_critique(corr, AgentId.VESTA, stance=Stance.AGREE),
            _make_critique(corr, AgentId.NYX, stance=Stance.DISAGREE, contrarian=True),
        ]
        decision = evaluate(proposal, critiques, corr)
        assert decision.contrarian_flag_raised is True

    def test_contrarian_flag_false_when_none(self):
        corr = uuid4()
        proposal = _make_proposal(corr)
        critiques = [
            _make_critique(corr, AgentId.APOLLO, stance=Stance.AGREE),
            _make_critique(corr, AgentId.HERMES, stance=Stance.AGREE),
            _make_critique(corr, AgentId.VESTA, stance=Stance.AGREE),
            _make_critique(corr, AgentId.NYX, stance=Stance.AGREE),
        ]
        decision = evaluate(proposal, critiques, corr)
        assert decision.contrarian_flag_raised is False

    def test_veto_and_contrarian_both_propagate(self):
        # Single critique with both signals. Veto wins outcome; contrarian
        # flag still propagates to DecisionMessage for ATLAS visibility.
        corr = uuid4()
        proposal = _make_proposal(corr)
        critiques = [
            _make_critique(corr, AgentId.NYX, stance=Stance.DISAGREE, veto=True, contrarian=True),
        ]
        decision = evaluate(proposal, critiques, corr)
        assert decision.outcome == DecisionOutcome.REJECTED
        assert decision.consensus_state.consensus_type == ConsensusType.VETOED
        assert decision.contrarian_flag_raised is True
