from __future__ import annotations

from .apollo_mock import ApolloMock
from .athena_mock import AthenaMock
from .atlas_mock import AtlasMock
from .base import BaseMockAgent, CycleResult, MockOrchestrator
from .fixtures import SCENARIOS, ScenarioDef
from .hermes_mock import HermesMock
from .nyx_mock import NyxMock
from .vesta_mock import VestaMock

__all__ = [
    "BaseMockAgent",
    "CycleResult",
    "MockOrchestrator",
    "ScenarioDef",
    "SCENARIOS",
    "AthenaMock",
    "ApolloMock",
    "HermesMock",
    "NyxMock",
    "VestaMock",
    "AtlasMock",
]


def build_orchestrator(repo) -> MockOrchestrator:
    """Convenience factory — wires all mock agents with the given repo."""
    return MockOrchestrator(
        athena=AthenaMock(),
        apollo=ApolloMock(),
        hermes=HermesMock(),
        nyx=NyxMock(),
        vesta=VestaMock(),
        atlas=AtlasMock(),
        repo=repo,
    )
