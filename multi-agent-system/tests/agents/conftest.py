"""Shared fixtures for agent unit tests."""
from __future__ import annotations

import pytest

from multi_agent.agents import SCENARIOS, build_orchestrator
from multi_agent.agents.fixtures import ScenarioDef


class CapturingRepository:
    """Records all persisted messages in memory; no DB required."""

    def __init__(self) -> None:
        self.proposals: list = []
        self.critiques: list = []
        self.decisions: list = []
        self.atlas_validations: list = []
        self.llm_costs: list = []

    def save_proposal(self, msg, **_): self.proposals.append(msg)
    def save_critique(self, msg, **_): self.critiques.append(msg)
    def save_decision(self, msg, **_): self.decisions.append(msg)
    def save_atlas_validation(self, msg, **_): self.atlas_validations.append(msg)
    def log_llm_cost(self, **kwargs): self.llm_costs.append(kwargs)

    @property
    def all_messages(self) -> list:
        return self.proposals + self.critiques + self.decisions + self.atlas_validations


@pytest.fixture
def repo() -> CapturingRepository:
    return CapturingRepository()


@pytest.fixture
def orchestrator(repo):
    return build_orchestrator(repo)


@pytest.fixture(params=list(SCENARIOS.keys()))
def scenario(request) -> ScenarioDef:
    return SCENARIOS[request.param]


@pytest.fixture(params=["all_agree", "nyx_dissents", "deep_disagreement",
                        "atlas_blocks", "high_conviction_solo"])
def all_scenarios(request) -> ScenarioDef:
    return SCENARIOS[request.param]
