"""
Example: How agents in the multi-agent trading system use the ClaudeRouter.

This file shows typical usage patterns for each agent type, demonstrating
the right task_type and criticality for common scenarios.

Run with: python examples/usage_example.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add parent dir to path so we can import router
sys.path.insert(0, str(Path(__file__).parent.parent))

from router import Criticality, get_router


# =============================================================================
# Example system prompts (truncated; in production these are 3000-5000 tokens)
# =============================================================================

ATHENA_SYSTEM_PROMPT = """
You are ATHENA, the quantitative systematic agent of a multi-agent trading system.

Identity: Skeptical, data-driven, patient. The voice that asks "what do the
numbers say, not what we believe?"

Archetype: Renaissance Technologies / Jim Simons.

Your specialty:
- Statistical mean reversion
- Pair trading via cointegration
- Systematic options selling: CSP, credit spreads, iron condors
- Strategies with N >= 100 historical occurrences and POP > 70%

Your framework:
- Every trade requires N >= 100 historical occurrences
- POP > 70% required to open
- Position sizing Kelly fraction 0.25x
- Mechanical exit at 50% max profit
- Zero discretionality post-entry

[... full prompt continues ~3000 more tokens ...]
"""

NYX_SYSTEM_PROMPT = """
You are NYX, the contrarian independent agent of a multi-agent trading system.

Identity: Radically independent, patient, skeptical of dominant narratives.
The voice that asks "where is the market wrong due to emotional contagion?"

[... full prompt continues ~3000 more tokens ...]
"""

ATLAS_SYSTEM_PROMPT = """
You are ATLAS, the portfolio guardian.

Your mandate is NOT alpha generation. Your mandate is to ensure the system
survives to generate alpha tomorrow.

[... full prompt continues ~4000 more tokens ...]
"""


# =============================================================================
# Example 1: Athena generates a CSP proposal (standard criticality)
# =============================================================================

def example_athena_proposal():
    """Athena evaluates MSFT for a CSP setup. Routes to Sonnet."""
    router = get_router("config/routing_rules.yaml")

    user_prompt = """
    Evaluate MSFT for a Cash Secured Put setup.

    Current data:
    - Price: $415.30
    - IV Rank: 62 (78th percentile last 12 months)
    - Support zone: 408-412 (tested 4 times in last 90 days)
    - Earnings: reported, next event in 89 days
    - Backtest of similar setups: 84 occurrences, win rate 73%, avg P&L +$340

    Generate a structured proposal following the standard format.
    """

    response = router.send(
        task_type="proposal_generation",
        system_prompt=ATHENA_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        agent="athena",
        criticality=Criticality.STANDARD,
    )

    print("=" * 70)
    print("EXAMPLE 1: Athena CSP Proposal (Sonnet expected)")
    print("=" * 70)
    print(f"Model used: {response.model_used}")
    print(f"Cost: ${response.cost.total_usd:.4f}")
    print(f"Latency: {response.latency_ms:.0f}ms")
    print(f"Cache reads: {response.cost.cache_read_tokens}")
    print(f"Cache writes: {response.cost.cache_creation_tokens}")
    print()


# =============================================================================
# Example 2: Nyx classifies sentiment of news (high volume → Haiku)
# =============================================================================

def example_nyx_sentiment_classification():
    """Nyx processes news headlines for sentiment. Routes to Haiku."""
    router = get_router("config/routing_rules.yaml")

    headlines = [
        "Tesla beats Q1 earnings estimates by 12%",
        "Fed officials signal possible rate cuts in H2",
        "China manufacturing PMI contracts for third month",
    ]

    for headline in headlines:
        response = router.send(
            task_type="sentiment_classification",
            system_prompt="Classify the sentiment of financial headlines as bullish/bearish/neutral with a score 0-100.",
            user_prompt=f"Headline: {headline}\n\nReturn JSON: {{sentiment, score, reason}}",
            agent="nyx",
            criticality=Criticality.STANDARD,
        )
        print(f"Headline: {headline[:50]}...")
        print(f"  Model: {response.model_used} | Cost: ${response.cost.total_usd:.5f}")
        print()


# =============================================================================
# Example 3: Complex consensus decision → Opus
# =============================================================================

def example_complex_consensus():
    """
    A complex disagreement between Athena, Apollo, and Nyx requires
    careful synthesis. Routes to Opus.
    """
    router = get_router("config/routing_rules.yaml")

    debate_context = """
    Trade proposal: Sell credit spread on SPX, 4500/4480, 30 DTE

    ATHENA (proposer): "Backtest shows 73% win rate. IV Rank 65. POP 78%. 
    Recommended size: 4% portfolio."

    APOLLO (disagrees): "Macro regime shifting. Curve is steepening, credit 
    spreads widening. Selling vol now is fighting the next cycle. Recommend 
    block or reduce size."

    NYX (disagrees): "AAII bull/bear in 92nd percentile, VIX in 8th percentile. 
    Selling vol when sentiment is extreme + vol is at lows is asymmetric risk. 
    Contrarian flag raised."

    HERMES (neutral): "No intraday flow signal either direction."

    VESTA (neutral): "No sector rotation implication."

    Synthesize a final decision with size modulation and conditions.
    """

    response = router.send(
        task_type="consensus_complex",
        system_prompt="You synthesize complex multi-agent debates into final trading decisions.",
        user_prompt=debate_context,
        agent=None,  # System-level decision
        criticality=Criticality.HIGH,
    )

    print("=" * 70)
    print("EXAMPLE 3: Complex Consensus Decision (Opus expected)")
    print("=" * 70)
    print(f"Model used: {response.model_used}")
    print(f"Cost: ${response.cost.total_usd:.4f}")
    print(f"This decision affects real money — Opus is justified.")
    print()


# =============================================================================
# Example 4: ATLAS in alert mode → Opus
# =============================================================================

def example_atlas_yellow_mode():
    """ATLAS in yellow mode evaluates exposure. Routes to Opus."""
    router = get_router("config/routing_rules.yaml")

    portfolio_state = """
    Current portfolio state:
    - Drawdown from peak: -3.8% (yellow zone)
    - Tech concentration: 33% (limit 35%)
    - Net beta: 1.42 (limit 1.5)
    - Net vega: -1850 (limit -2000)
    - 4 positions with rolling correlation > 0.7

    Proposed new trade: Athena CSP on AAPL, 5% portfolio size
    Pre-trade impact:
    - Tech concentration would go to 38% (BREACH)
    - Net vega would go to -2080 (BREACH)

    Decide: APPROVE / APPROVE_WITH_CONDITIONS / BLOCK
    Provide rationale and any required modifications.
    """

    response = router.send(
        task_type="atlas_validation_alert",
        system_prompt=ATLAS_SYSTEM_PROMPT,
        user_prompt=portfolio_state,
        agent="atlas",
        criticality=Criticality.HIGH,
    )

    print("=" * 70)
    print("EXAMPLE 4: ATLAS Yellow Mode Validation (Opus expected)")
    print("=" * 70)
    print(f"Model used: {response.model_used}")
    print(f"Cost: ${response.cost.total_usd:.4f}")
    print()


# =============================================================================
# Example 5: Daily report generation → Sonnet + Batch API
# =============================================================================

def example_daily_report():
    """End-of-day report. Routes to Sonnet via Batch API for 50% discount."""
    router = get_router("config/routing_rules.yaml")

    daily_data = """
    Trading day summary:
    - Trades opened: 5 (3 Athena, 1 Apollo, 1 Hermes)
    - Trades closed: 3 (2 winners, 1 loser)
    - Total P&L: +$2,340 (0.23% portfolio)
    - Drawdown: 1.2%
    - Notable events: NVDA gapped up 4% on AI news
    
    Generate the structured daily report.
    """

    response = router.send(
        task_type="daily_report",
        system_prompt="Generate structured daily trading reports.",
        user_prompt=daily_data,
        agent=None,
        criticality=Criticality.STANDARD,
    )

    print("=" * 70)
    print("EXAMPLE 5: Daily Report (Sonnet via Batch API expected)")
    print("=" * 70)
    print(f"Model used: {response.model_used}")
    print(f"Used Batch API: {response.cost.used_batch_api}")
    print(f"Cost: ${response.cost.total_usd:.4f}")
    print()


# =============================================================================
# Example 6: Cost summary at end of session
# =============================================================================

def show_cost_summary():
    """Display cost summary and check targets."""
    router = get_router("config/routing_rules.yaml")
    summary = router.get_cost_summary()

    print("=" * 70)
    print("COST SUMMARY")
    print("=" * 70)
    print(json.dumps(summary, indent=2))
    print()

    # Check targets
    targets_check = router.check_targets()
    if targets_check["alerts"]:
        print("⚠️  ALERTS:")
        for alert in targets_check["alerts"]:
            print(f"  - {alert}")
    else:
        print("✓ All targets within range")
    print()


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print()
    print("Claude Router — Usage Examples")
    print("=" * 70)
    print()
    print("NOTE: These examples require ANTHROPIC_API_KEY to be set.")
    print("They will make real API calls. Comment out examples if testing.")
    print()

    # Uncomment to run examples (will make real API calls)
    # example_athena_proposal()
    # example_nyx_sentiment_classification()
    # example_complex_consensus()
    # example_atlas_yellow_mode()
    # example_daily_report()
    # show_cost_summary()

    print("To run examples, set ANTHROPIC_API_KEY and uncomment in __main__")
