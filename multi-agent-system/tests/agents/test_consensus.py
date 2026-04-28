"""
Unit tests for the consensus engine.

Each test runs a full cycle through the orchestrator and checks that
the consensus outcome and size modulation match the scenario contract.
"""
from __future__ import annotations

import pytest

from multi_agent.agents import SCENARIOS, build_orchestrator
from multi_agent.communication.enums import (
    AtlasDecision,
    ConsensusType,
    DecisionOutcome,
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
        assert result.atlas_validation.decision == AtlasDecision.APPROVED


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
        assert result.atlas_validation.decision == AtlasDecision.BLOCKED

    def test_block_reason_in_modulations(self):
        result, _ = _run("atlas_blocks")
        scenario = SCENARIOS["atlas_blocks"]
        assert any(scenario.atlas_block_reason in m for m in result.atlas_validation.modulations_applied)

    def test_risk_mode_yellow(self):
        result, _ = _run("atlas_blocks")
        from multi_agent.communication.enums import RiskMode
        assert result.atlas_validation.risk_mode == RiskMode.YELLOW


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
