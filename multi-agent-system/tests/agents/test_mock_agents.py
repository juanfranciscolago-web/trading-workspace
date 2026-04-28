"""
Unit tests for individual mock agents.

All tests use CapturingRepository — no DB required.
"""
from __future__ import annotations

import random
from uuid import uuid4

import pytest

from multi_agent.agents import (
    ApolloMock,
    AthenaMock,
    AtlasMock,
    HermesMock,
    NyxMock,
    VestaMock,
)
from multi_agent.agents import SCENARIOS
from multi_agent.communication.enums import (
    AgentId,
    AtlasDecision,
    DecisionOutcome,
    RiskMode,
    Stance,
)
from multi_agent.communication.schemas import DecisionMessage


# ── ATHENA ────────────────────────────────────────────────────────────────────

class TestAthenaMock:
    def setup_method(self):
        self.agent = AthenaMock()
        self.scenario = SCENARIOS["all_agree"]
        self.rng = random.Random(42)
        self.corr = uuid4()

    def test_returns_proposal_message(self):
        from multi_agent.communication.schemas import ProposalMessage
        msg = self.agent.generate_proposal(self.scenario, self.rng, self.corr)
        assert isinstance(msg, ProposalMessage)

    def test_agent_id_is_athena(self):
        msg = self.agent.generate_proposal(self.scenario, self.rng, self.corr)
        assert msg.agent_id == AgentId.ATHENA

    def test_correlation_id_propagated(self):
        msg = self.agent.generate_proposal(self.scenario, self.rng, self.corr)
        assert msg.correlation_id == self.corr

    def test_conviction_score_matches_scenario(self):
        msg = self.agent.generate_proposal(self.scenario, self.rng, self.corr)
        assert msg.conviction_score == self.scenario.conviction_score

    def test_ticker_matches_scenario(self):
        msg = self.agent.generate_proposal(self.scenario, self.rng, self.corr)
        assert msg.trade.ticker == self.scenario.ticker

    def test_sizing_positive(self):
        msg = self.agent.generate_proposal(self.scenario, self.rng, self.corr)
        assert msg.sizing.proposed_size_pct_portfolio > 0
        assert float(msg.sizing.proposed_size_usd) > 0

    def test_structure_has_at_least_one_leg(self):
        msg = self.agent.generate_proposal(self.scenario, self.rng, self.corr)
        assert len(msg.trade.structure.legs) >= 1

    def test_conviction_score_in_range(self):
        msg = self.agent.generate_proposal(self.scenario, self.rng, self.corr)
        assert 0 <= msg.conviction_score <= 100

    def test_reproducible_with_same_seed(self):
        rng1, rng2 = random.Random(99), random.Random(99)
        corr = uuid4()
        m1 = self.agent.generate_proposal(self.scenario, rng1, corr)
        m2 = self.agent.generate_proposal(self.scenario, rng2, corr)
        # Strike should be identical with same seed (same rng state at same call)
        assert m1.trade.structure.legs[0].strike == m2.trade.structure.legs[0].strike


# ── Critic agents ─────────────────────────────────────────────────────────────

class TestCriticAgents:
    """Shared tests for all 4 critiquing agents."""

    @pytest.mark.parametrize("agent_cls,agent_key", [
        (ApolloMock, "apollo"),
        (HermesMock, "hermes"),
        (NyxMock,    "nyx"),
        (VestaMock,  "vesta"),
    ])
    def test_stance_matches_scenario(self, agent_cls, agent_key):
        from multi_agent.communication.schemas import ProposalMessage
        scenario = SCENARIOS["all_agree"]
        agent = agent_cls()
        rng = random.Random(7)
        corr = uuid4()
        # Create a minimal proposal for critique
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        critique = agent.critique(proposal, scenario, rng, corr)
        expected_stance = scenario.agent_stances[agent_key]
        assert critique.stance == expected_stance

    @pytest.mark.parametrize("agent_cls,agent_key", [
        (ApolloMock, "apollo"),
        (HermesMock, "hermes"),
        (NyxMock,    "nyx"),
        (VestaMock,  "vesta"),
    ])
    def test_correlation_id_propagated(self, agent_cls, agent_key):
        scenario = SCENARIOS["nyx_dissents"]
        agent = agent_cls()
        rng = random.Random(7)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        critique = agent.critique(proposal, scenario, rng, corr)
        assert critique.correlation_id == corr

    @pytest.mark.parametrize("agent_cls,agent_key", [
        (ApolloMock, "apollo"),
        (HermesMock, "hermes"),
        (NyxMock,    "nyx"),
        (VestaMock,  "vesta"),
    ])
    def test_parent_message_id_is_proposal(self, agent_cls, agent_key):
        scenario = SCENARIOS["all_agree"]
        agent = agent_cls()
        rng = random.Random(7)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        critique = agent.critique(proposal, scenario, rng, corr)
        assert critique.parent_message_id == proposal.message_id


class TestNyxContrarian:
    def test_contrarian_flag_set_in_nyx_dissents(self):
        scenario = SCENARIOS["nyx_dissents"]
        agent = NyxMock()
        rng = random.Random(7)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        critique = agent.critique(proposal, scenario, rng, corr)
        assert critique.contrarian_flag_raised is True
        assert critique.stance == Stance.DISAGREE

    def test_contrarian_flag_not_set_in_all_agree(self):
        scenario = SCENARIOS["all_agree"]
        agent = NyxMock()
        rng = random.Random(7)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        critique = agent.critique(proposal, scenario, rng, corr)
        assert critique.contrarian_flag_raised is False


# ── ATLAS mock ────────────────────────────────────────────────────────────────

class TestAtlasMock:
    def _make_decision(self, outcome: DecisionOutcome) -> DecisionMessage:
        from multi_agent.communication.enums import AgentId, ConsensusType
        from multi_agent.communication.schemas import ConsensusState
        return DecisionMessage(
            agent_id=AgentId.ATLAS,
            correlation_id=uuid4(),
            outcome=outcome,
            consensus_state=ConsensusState(
                agree=[], disagree=[], neutral=[], consensus_type=ConsensusType.UNANIMOUS
            ),
        )

    def test_approves_when_scenario_green(self):
        scenario = SCENARIOS["all_agree"]
        agent = AtlasMock()
        rng = random.Random(42)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        decision = self._make_decision(DecisionOutcome.APPROVED)
        result = agent.validate(proposal, decision, scenario, rng, corr)
        assert result.decision == AtlasDecision.APPROVED

    def test_blocks_when_scenario_atlas_blocks(self):
        scenario = SCENARIOS["atlas_blocks"]
        agent = AtlasMock()
        rng = random.Random(42)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        decision = self._make_decision(DecisionOutcome.APPROVED)
        result = agent.validate(proposal, decision, scenario, rng, corr)
        assert result.decision == AtlasDecision.BLOCKED

    def test_risk_mode_yellow_when_blocking(self):
        scenario = SCENARIOS["atlas_blocks"]
        agent = AtlasMock()
        rng = random.Random(42)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        decision = self._make_decision(DecisionOutcome.APPROVED)
        result = agent.validate(proposal, decision, scenario, rng, corr)
        assert result.risk_mode == RiskMode.YELLOW

    def test_risk_mode_green_when_not_blocking(self):
        scenario = SCENARIOS["all_agree"]
        agent = AtlasMock()
        rng = random.Random(42)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        decision = self._make_decision(DecisionOutcome.APPROVED)
        result = agent.validate(proposal, decision, scenario, rng, corr)
        assert result.risk_mode == RiskMode.GREEN

    def test_stress_tests_have_three_scenarios(self):
        scenario = SCENARIOS["all_agree"]
        agent = AtlasMock()
        rng = random.Random(42)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        decision = self._make_decision(DecisionOutcome.APPROVED)
        result = agent.validate(proposal, decision, scenario, rng, corr)
        assert len(result.stress_test_results) == 3

    def test_correlation_id_propagated(self):
        scenario = SCENARIOS["all_agree"]
        agent = AtlasMock()
        rng = random.Random(42)
        corr = uuid4()
        proposal = AthenaMock().generate_proposal(scenario, rng, corr)
        decision = self._make_decision(DecisionOutcome.APPROVED)
        result = agent.validate(proposal, decision, scenario, rng, corr)
        assert result.correlation_id == corr
