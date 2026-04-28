"""
Integration tests for MockOrchestrator — no DB required.

Tests that the full pipeline produces internally consistent output
for all 5 scenarios.
"""
from __future__ import annotations

import pytest

from multi_agent.agents import SCENARIOS, build_orchestrator
from multi_agent.communication.enums import MessageType
from multi_agent.communication.schemas import (
    AtlasValidationMessage,
    CritiqueMessage,
    DecisionMessage,
    ProposalMessage,
)

from .conftest import CapturingRepository


def _run(name: str):
    repo = CapturingRepository()
    orc = build_orchestrator(repo)
    result = orc.run_cycle(SCENARIOS[name])
    return result, repo


class TestOrchestratorContract:
    """Run each scenario and verify the message set is structurally correct."""

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_produces_one_proposal(self, scenario_name):
        _, repo = _run(scenario_name)
        assert len(repo.proposals) == 1
        assert isinstance(repo.proposals[0], ProposalMessage)

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_produces_four_critiques(self, scenario_name):
        _, repo = _run(scenario_name)
        assert len(repo.critiques) == 4
        assert all(isinstance(c, CritiqueMessage) for c in repo.critiques)

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_produces_one_decision(self, scenario_name):
        _, repo = _run(scenario_name)
        assert len(repo.decisions) == 1
        assert isinstance(repo.decisions[0], DecisionMessage)

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_produces_one_atlas_validation(self, scenario_name):
        _, repo = _run(scenario_name)
        assert len(repo.atlas_validations) == 1
        assert isinstance(repo.atlas_validations[0], AtlasValidationMessage)

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_all_messages_share_correlation_id(self, scenario_name):
        result, repo = _run(scenario_name)
        corr = result.correlation_id
        for msg in repo.all_messages:
            assert msg.correlation_id == corr, (
                f"{type(msg).__name__} has wrong correlation_id"
            )

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_critique_parent_is_proposal(self, scenario_name):
        result, repo = _run(scenario_name)
        proposal_id = result.proposal.message_id
        for c in repo.critiques:
            assert c.parent_message_id == proposal_id

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_decision_parent_is_proposal(self, scenario_name):
        result, _ = _run(scenario_name)
        assert result.decision.parent_message_id == result.proposal.message_id

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_atlas_parent_is_decision(self, scenario_name):
        result, _ = _run(scenario_name)
        assert result.atlas_validation.parent_message_id == result.decision.message_id

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_all_four_critics_present(self, scenario_name):
        result, _ = _run(scenario_name)
        critic_agents = {c.agent_id.value for c in result.critiques}
        assert critic_agents == {"APOLLO", "HERMES", "NYX", "VESTA"}

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    def test_seeded_run_is_reproducible(self, scenario_name):
        scenario = SCENARIOS[scenario_name]
        repo_a = CapturingRepository()
        repo_b = CapturingRepository()
        orc = build_orchestrator(repo_a)
        r_a = orc.run_cycle(scenario, seed=scenario.seed)
        orc2 = build_orchestrator(repo_b)
        r_b = orc2.run_cycle(scenario, seed=scenario.seed)
        # Proposals with same seed should produce same conviction and ticker
        assert r_a.proposal.conviction_score == r_b.proposal.conviction_score
        assert r_a.proposal.trade.ticker == r_b.proposal.trade.ticker
        assert r_a.decision.outcome == r_b.decision.outcome


class TestOrchestratorTotalMessages:
    def test_total_message_count_is_seven(self):
        # 1 proposal + 4 critiques + 1 decision + 1 atlas = 7
        _, repo = _run("all_agree")
        assert len(repo.all_messages) == 7
