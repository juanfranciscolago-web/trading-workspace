"""
BaseAgent — abstract base for real (LLM-backed) trading agents.

Distinguished from BaseMockAgent (in `base.py`): real agents make LLM calls
via ClaudeRouter to generate proposals. Concrete subclasses (AthenaAgent in
Sprint 3, ApolloAgent + HermesAgent in Sprint 4, etc.) wire in their specific
data dependencies and prompts.

Sprint 3 scope: only `generate_proposal` is part of the contract. Critic and
validator methods (used by APOLLO/HERMES/NYX/VESTA in Sprint 4 and ATLAS-real
later) are added when those agents land.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from claude_router.router import ClaudeRouter

from multi_agent.communication.enums import AgentId
from multi_agent.communication.schemas import ProposalMessage


class BaseAgent(ABC):
    """Abstract base for real trading agents.

    Subclass contract:
      - Class attribute `agent_id: AgentId` declared.
      - Implement `generate_proposal(correlation_id) -> ProposalMessage`.
    """
    agent_id: AgentId  # must be declared on each subclass

    def __init__(self, claude_router: ClaudeRouter) -> None:
        self._claude_router = claude_router

    @abstractmethod
    def generate_proposal(self, correlation_id: UUID) -> ProposalMessage | None:
        """Generate a trading proposal, or return None if the agent declines.

        Concrete agents fetch their own market data (via injected data layer
        or similar) and call self._claude_router.send(...) to get the LLM
        output, then parse and validate it into a ProposalMessage. Return
        None when the LLM responds with a "no setup" decision (Shape B in
        ATHENA's prompt convention) — the agent saw the market state but
        declined to propose. Callers must handle both branches.
        """
