"""
Unit tests for APOLLO system prompt and user prompt builder.

Verifies:
- SYSTEM_PROMPT length budget (< 4500 chars — APOLLO has 5 decision
  dimensions vs ATHENA's 1, so a larger budget than ATHENA's 4000 is
  justified).
- SYSTEM_PROMPT contains identity / framework / stance criteria / veto /
  contrarian flag / output schema.
- build_user_prompt() embeds the proposal JSON + market state JSON + task
  instruction + Sprint 4 data caveat.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from multi_agent.agents.apollo_prompt import SYSTEM_PROMPT, build_user_prompt
from multi_agent.communication.enums import (
    AgentId,
    AssetClass,
    Direction,
    OptionType,
    StrategyType,
)
from multi_agent.communication.schemas import (
    DataSignature,
    OptionLeg,
    ProposalMessage,
    Thesis,
    TradeDetails,
    TradeSizing,
    TradeStructure,
)
from multi_agent.data_layer import StubDataLayer


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def market_state():
    """Default-seeded MarketState used by the user-prompt builder tests."""
    return StubDataLayer().snapshot()


@pytest.fixture
def proposal():
    """Canonical ATHENA-style ProposalMessage for build_user_prompt tests."""
    return ProposalMessage(
        agent_id=AgentId.ATHENA,
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


# ── SYSTEM_PROMPT tests ───────────────────────────────────────────────────────

class TestSystemPrompt:

    def test_system_prompt_length_budget(self):
        """Guard against prompt bloat. Budget 4500 reflects APOLLO's 5
        decision dimensions (stance, veto, contrarian_flag, evidence,
        concern) vs ATHENA's 1 (propose or not)."""
        assert len(SYSTEM_PROMPT) < 4500, (
            f"SYSTEM_PROMPT is {len(SYSTEM_PROMPT)} chars, budget is 4500"
        )

    def test_system_prompt_mentions_apollo_identity(self):
        """Must establish APOLLO's identity and persona."""
        assert "APOLLO" in SYSTEM_PROMPT
        assert "contrarian" in SYSTEM_PROMPT.lower()
        assert "macro" in SYSTEM_PROMPT.lower()

    def test_system_prompt_contains_critique_framework(self):
        """The critique framework section must be present with distinctive
        phrases from the 4 framing questions."""
        assert "Critique framework" in SYSTEM_PROMPT
        assert "statistical thesis" in SYSTEM_PROMPT.lower()
        assert "counter-thesis" in SYSTEM_PROMPT.lower()

    def test_system_prompt_contains_stance_criteria(self):
        """All 4 stances must be documented in the criteria section."""
        for stance in ("AGREE", "AGREE_WITH_CONDITIONS", "DISAGREE", "NEUTRAL"):
            assert stance in SYSTEM_PROMPT, f"missing stance: {stance}"

    def test_system_prompt_contains_veto_criterion(self):
        """Veto criterion must be present with 'sparingly' guidance."""
        assert "veto_request" in SYSTEM_PROMPT
        assert "sparingly" in SYSTEM_PROMPT.lower()

    def test_system_prompt_contains_contrarian_flag_criterion(self):
        """Contrarian flag criterion must be present and linked to
        productive-dissent semantics."""
        assert "contrarian_flag_raised" in SYSTEM_PROMPT
        assert "productive" in SYSTEM_PROMPT.lower()

    def test_system_prompt_specifies_json_output(self):
        """Schema must mention all top-level fields the LLM produces."""
        for key in (
            "stance",
            "argument",
            "veto_request",
            "contrarian_flag_raised",
            "alternative_proposal",
        ):
            assert f'"{key}"' in SYSTEM_PROMPT, f"missing schema key: {key}"

    def test_system_prompt_excludes_injected_fields(self):
        """Schema must NOT include fields injected by ApolloAgent post-parse.
        Each should appear at most once (in the explicit 'Do NOT include' line).
        Uses word-boundary regex because some fields are substrings of others
        (message_id is a substring of parent_message_id)."""
        excluded_fields = (
            "correlation_id",
            "agent_id",
            "message_type",
            "message_id",
            "parent_message_id",
        )
        for key in excluded_fields:
            matches = re.findall(rf"\b{key}\b", SYSTEM_PROMPT)
            assert len(matches) <= 1, (
                f"injected field '{key}' appears {len(matches)} times"
            )


# ── build_user_prompt tests ───────────────────────────────────────────────────

class TestBuildUserPrompt:

    def test_embeds_proposal_json(self, proposal, market_state):
        """The proposal must be visible inside the prompt."""
        prompt = build_user_prompt(proposal, market_state)
        assert "ProposalMessage was generated by ATHENA" in prompt
        # Proposal-specific content from the canonical proposal fixture
        assert "MSFT" in prompt
        assert "CSP" in prompt

    def test_embeds_market_state_json(self, proposal, market_state):
        """The last fenced json block (market state) must be parseable
        with the expected MarketState keys."""
        prompt = build_user_prompt(proposal, market_state)
        matches = re.findall(r"```json\n(.*?)\n```", prompt, re.DOTALL)
        assert len(matches) >= 2, f"expected >=2 json blocks, got {len(matches)}"
        parsed = json.loads(matches[-1])
        assert "tickers" in parsed
        assert "correlations" in parsed
        assert "timestamp" in parsed

    def test_mentions_sprint4_data_caveat(self, proposal, market_state):
        """User prompt must flag Sprint 4 macro-data limitation so the LLM
        relies on trained knowledge for richer indicators."""
        prompt = build_user_prompt(proposal, market_state)
        assert "Sprint 4" in prompt
        assert "macro" in prompt.lower()

    def test_includes_task_section(self, proposal, market_state):
        """User prompt must include a Task section directing the LLM to
        produce a stance."""
        prompt = build_user_prompt(proposal, market_state)
        assert "# Task" in prompt
        assert "stance" in prompt.lower()
