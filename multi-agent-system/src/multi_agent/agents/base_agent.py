"""
BaseAgent — abstract base for real (LLM-backed) trading agents.

Distinguished from BaseMockAgent (in `base.py`): real agents make LLM calls
via ClaudeRouter to generate proposals or critique them. Concrete subclasses
(AthenaAgent in Sprint 3 — proposer; ApolloAgent in Sprint 4 B.4.2 — critic)
wire in their specific data dependencies and prompts.

Sprint 3 introduced `generate_proposal` (abstract — required by every
subclass). Sprint 4 B.4.2 introduces `critique_proposal` as a non-abstract
default raising NotImplementedError, so proposer-only agents (ATHENA)
inherit a clean default and critic agents (APOLLO and future HERMES / NYX /
VESTA) override it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from claude_router.router import ClaudeRouter

from multi_agent.communication.enums import AgentId
from multi_agent.communication.schemas import CritiqueMessage, ProposalMessage
from multi_agent.data_layer import MarketState


class BaseAgent(ABC):
    """Abstract base for real trading agents.

    Subclass contract:
      - Class attribute `agent_id: AgentId` declared.
      - Implement `generate_proposal(correlation_id) -> ProposalMessage` for
        proposer agents (ATHENA).
      - Override `critique_proposal(proposal, market_state, correlation_id)`
        for critic agents (APOLLO and future HERMES / NYX / VESTA).
      - Agents that only fulfill one role inherit the default
        NotImplementedError for the other.
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

    def critique_proposal(
        self,
        proposal: ProposalMessage,
        market_state: MarketState,
        correlation_id: UUID,
    ) -> CritiqueMessage:
        """Critique a proposal from another agent, producing a CritiqueMessage.

        Critic agents (APOLLO contrarian/devil's-advocate in Sprint 4 B.4.2,
        future HERMES / NYX / VESTA) override this to call
        ClaudeRouter.send(...) with their own system prompt + lens, parse
        the LLM response, and assemble a validated CritiqueMessage with
        stance, argument (summary + evidence + concern +
        data_that_would_change_my_mind), veto_request, and
        contrarian_flag_raised.

        Default raises NotImplementedError — proposer-only agents (ATHENA)
        do not implement critique_proposal and would never have it called
        on them in the worker chain.
        """
        raise NotImplementedError(
            f"{type(self).__name__} (agent_id={self.agent_id.value}) "
            f"does not implement critique_proposal. This method is for "
            f"critic agents (APOLLO/HERMES/NYX/VESTA)."
        )
