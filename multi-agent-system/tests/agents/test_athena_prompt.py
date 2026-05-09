"""
Unit tests for ATHENA system prompt and user prompt builder.

Verifies:
- SYSTEM_PROMPT length budget (< 4000 chars).
- SYSTEM_PROMPT contains identity / strategies / no_setup escape / output schema.
- build_user_prompt() embeds all universe tickers and a valid JSON block.
"""
from __future__ import annotations

import json
import re

import pytest

from multi_agent.agents.athena_prompt import SYSTEM_PROMPT, build_user_prompt
from multi_agent.data_layer import StubDataLayer, TICKER_UNIVERSE


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def market_state():
    """Default-seeded MarketState used by the user-prompt builder tests."""
    return StubDataLayer().snapshot()


# ── SYSTEM_PROMPT tests ───────────────────────────────────────────────────────

class TestSystemPrompt:

    def test_system_prompt_length_budget(self):
        """Guard against accidental prompt bloat."""
        assert len(SYSTEM_PROMPT) < 4000, (
            f"SYSTEM_PROMPT is {len(SYSTEM_PROMPT)} chars, budget is 4000"
        )

    def test_system_prompt_mentions_athena_identity(self):
        """Must establish ATHENA's identity and persona."""
        assert "ATHENA" in SYSTEM_PROMPT
        assert "systematic" in SYSTEM_PROMPT.lower()

    def test_system_prompt_mentions_strategies(self):
        """Must list ATHENA's specialty strategies."""
        assert "CSP" in SYSTEM_PROMPT
        assert "CREDIT_SPREAD" in SYSTEM_PROMPT
        assert "IRON_CONDOR" in SYSTEM_PROMPT

    def test_system_prompt_includes_no_setup_escape(self):
        """Must document the Shape B escape hatch."""
        assert "no_setup" in SYSTEM_PROMPT
        assert "reason" in SYSTEM_PROMPT
        assert "Shape B" in SYSTEM_PROMPT

    def test_system_prompt_includes_output_schema_keys(self):
        """Schema must mention all top-level fields the LLM produces."""
        for key in (
            "trade",
            "thesis",
            "conviction_score",
            "sizing",
            "self_acknowledged_biases",
        ):
            assert f'"{key}"' in SYSTEM_PROMPT, f"missing schema key: {key}"

    def test_system_prompt_excludes_injected_fields(self):
        """Schema must NOT include fields injected by AthenaAgent post-parse."""
        # These appear ONLY in the "Do NOT include" instruction line
        excluded_fields = ("correlation_id", "agent_id", "message_type", "data_signature")
        for key in excluded_fields:
            # field should appear at most once (in the explicit "Do NOT include" line)
            assert SYSTEM_PROMPT.count(key) <= 1, (
                f"injected field '{key}' appears {SYSTEM_PROMPT.count(key)} times"
            )


# ── build_user_prompt tests ───────────────────────────────────────────────────

class TestBuildUserPrompt:

    def test_includes_all_universe_tickers(self, market_state):
        prompt = build_user_prompt(market_state)
        for ticker in TICKER_UNIVERSE:
            assert ticker in prompt, f"missing ticker: {ticker}"

    def test_embeds_valid_json_block(self, market_state):
        """The ```json ... ``` fenced block must be parseable JSON."""
        prompt = build_user_prompt(market_state)
        # Extract content between ```json and ``` markers
        match = re.search(r"```json\n(.*?)\n```", prompt, re.DOTALL)
        assert match is not None, "no fenced json block found"
        parsed = json.loads(match.group(1))
        assert "tickers" in parsed
        assert "correlations" in parsed
        assert "timestamp" in parsed

    def test_includes_task_section(self, market_state):
        """User prompt must include a Task section directing the LLM."""
        prompt = build_user_prompt(market_state)
        assert "# Task" in prompt
        assert "ATHENA" in prompt
