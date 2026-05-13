"""Tests for Sprint 5 data caveat in ATHENA system prompt (S.5.6f)."""
from __future__ import annotations

from multi_agent.agents.athena_prompt import SYSTEM_PROMPT


def test_prompt_mentions_iv_rank_placeholder():
    """ADR-004 D3 honored: iv_rank placeholder must be explicit in prompt."""
    assert "placeholder" in SYSTEM_PROMPT
    assert "iv_rank" in SYSTEM_PROMPT
    assert "50.0" in SYSTEM_PROMPT


def test_prompt_clarifies_25_delta_skew_semantics():
    """SkewSnapshot legacy docstring mentions '1σ moves' but ADR-004 D5
    establishes 25-delta. Caveat must disambiguate for LLM."""
    assert "25-delta" in SYSTEM_PROMPT
    assert "1σ" in SYSTEM_PROMPT  # mentions but as "NOT 1σ moves"
