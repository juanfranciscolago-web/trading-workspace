"""Tests for ATHENA system prompt data semantics (S.5.6f base + S.6.iv-d D5)."""
from __future__ import annotations

from multi_agent.agents.athena_prompt import SYSTEM_PROMPT


def test_prompt_describes_iv_rank_progressive_semantics():
    """ADR-005 D5 progressive disclosure semantics surfaced to ATHENA (S.6.iv-d).

    Validates that the prompt describes:
    - iv_rank field reference,
    - ADR-005 mention (anchor for D5 semantics),
    - 252-sample threshold (full percentile),
    - bootstrap phase mention (N<10 fallback),
    - 50.0 placeholder value (fallback semantic).
    """
    assert "iv_rank" in SYSTEM_PROMPT
    assert "ADR-005" in SYSTEM_PROMPT
    assert "252" in SYSTEM_PROMPT
    assert "bootstrap" in SYSTEM_PROMPT.lower()
    assert "50.0" in SYSTEM_PROMPT


def test_prompt_clarifies_25_delta_skew_semantics():
    """SkewSnapshot legacy docstring mentions '1σ moves' but ADR-004 D5
    establishes 25-delta. Caveat must disambiguate for LLM."""
    assert "25-delta" in SYSTEM_PROMPT
    assert "1σ" in SYSTEM_PROMPT  # mentions but as "NOT 1σ moves"
