"""
Unit tests for BaseAgent abstract.
No LLM, no DB — ClaudeRouter is mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multi_agent.agents.base_agent import BaseAgent
from multi_agent.communication.enums import AgentId
from multi_agent.communication.schemas import ProposalMessage


# ── Test fixture: minimal concrete subclass ───────────────────────────────────

class _ConcreteAgent(BaseAgent):
    """Minimal concrete subclass for testing the BaseAgent contract."""
    agent_id = AgentId.ATHENA

    def generate_proposal(self, correlation_id):
        return MagicMock(spec=ProposalMessage)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBaseAgent:

    def test_cannot_instantiate_abstract_directly(self):
        """BaseAgent has abstract methods — cannot instantiate."""
        assert BaseAgent.__abstractmethods__ == frozenset({"generate_proposal"})
        with pytest.raises(TypeError, match="abstract"):
            BaseAgent(MagicMock())  # type: ignore[abstract]

    def test_subclass_stores_router(self):
        """Constructor stores claude_router as private attribute."""
        router = MagicMock()
        agent = _ConcreteAgent(router)
        assert agent._claude_router is router

    def test_subclass_inherits_agent_id(self):
        """Subclass class-attribute agent_id is accessible."""
        agent = _ConcreteAgent(MagicMock())
        assert agent.agent_id == AgentId.ATHENA

    def test_subclass_must_implement_generate_proposal(self):
        """Subclass without generate_proposal cannot be instantiated."""
        class _IncompleteAgent(BaseAgent):
            agent_id = AgentId.APOLLO
            # generate_proposal not implemented

        with pytest.raises(TypeError):
            _IncompleteAgent(MagicMock())  # type: ignore[abstract]
