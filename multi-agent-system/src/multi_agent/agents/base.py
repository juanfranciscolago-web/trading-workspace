"""
Base class for mock agents + synchronous orchestrator.

MockOrchestrator drives one full trade cycle:
  ATHENA → [APOLLO, HERMES, NYX, VESTA critiques] → consensus → ATLAS validation
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID, uuid4

from multi_agent.communication.enums import AgentId
from multi_agent.communication.schemas import (
    AtlasValidationMessage,
    CritiqueMessage,
    DecisionMessage,
    ProposalMessage,
)

from . import consensus as consensus_engine
from .fixtures import ScenarioDef


class BaseMockAgent(ABC):
    agent_id: AgentId  # declared on each subclass


@dataclass
class CycleResult:
    correlation_id: UUID
    proposal: ProposalMessage
    critiques: list[CritiqueMessage]
    decision: DecisionMessage
    atlas_validation: AtlasValidationMessage


class MockOrchestrator:
    """
    Drives a single trade cycle synchronously.

    repo: anything with save_proposal / save_critique / save_decision /
          save_atlas_validation methods. Pass a CapturingRepository for
          tests or a real MessageRepository for integration runs.
    """

    def __init__(
        self,
        athena,
        apollo,
        hermes,
        nyx,
        vesta,
        atlas,
        repo,
    ) -> None:
        self._athena = athena
        self._critics = [apollo, hermes, nyx, vesta]
        self._atlas = atlas
        self._repo = repo

    def run_cycle(self, scenario: ScenarioDef, seed: int | None = None) -> CycleResult:
        if seed is None:
            seed = scenario.seed
        rng = random.Random(seed)
        correlation_id = uuid4()

        # Phase 1 — ATHENA proposes
        proposal = self._athena.generate_proposal(scenario, rng, correlation_id)
        self._repo.save_proposal(proposal)

        # Phase 2 — Critics evaluate
        critiques: list[CritiqueMessage] = []
        for agent in self._critics:
            critique = agent.critique(proposal, scenario, rng, correlation_id)
            self._repo.save_critique(critique)
            critiques.append(critique)

        # Phase 3 — Consensus
        decision = consensus_engine.evaluate(proposal, critiques, correlation_id)
        self._repo.save_decision(decision)

        # Phase 4 — ATLAS validation
        atlas_validation = self._atlas.validate(
            proposal, decision, scenario, rng, correlation_id
        )
        self._repo.save_atlas_validation(atlas_validation)

        return CycleResult(
            correlation_id=correlation_id,
            proposal=proposal,
            critiques=critiques,
            decision=decision,
            atlas_validation=atlas_validation,
        )
