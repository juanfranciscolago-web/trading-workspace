"""
Scenario definitions for mock agents.

Each ScenarioDef fully specifies a market context + agent behaviour
for a named test scenario. The seed controls minor numeric variations
(strikes, exact sizing) while preserving the outcome.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from multi_agent.communication.enums import AssetClass, Stance, StrategyType


@dataclass(frozen=True)
class ScenarioDef:
    name: str
    seed: int
    ticker: str
    asset_class: AssetClass
    strategy_type: StrategyType
    # ATHENA's conviction score (0-100)
    conviction_score: int
    # Proposed portfolio allocation (%)
    proposed_size_pct: float
    # Mock price of the underlying used for option structure
    mock_price: float
    # Stances keyed by lowercase agent_id for the 4 critiquing agents
    agent_stances: dict[str, Stance]
    # Agents that raise the contrarian flag (lowercase agent_ids)
    contrarian_agents: frozenset[str] = field(default_factory=frozenset)
    # Whether ATLAS should block the trade
    atlas_block: bool = False
    atlas_block_reason: str = ""
    # Simulated portfolio exposure for ATLAS mock
    buying_power_used_pct: float = 22.0


SCENARIOS: dict[str, ScenarioDef] = {
    # ── 1. All four critics agree ─────────────────────────────────────────────
    "all_agree": ScenarioDef(
        name="all_agree",
        seed=1001,
        ticker="MSFT",
        asset_class=AssetClass.OPTION,
        strategy_type=StrategyType.CSP,
        conviction_score=78,
        proposed_size_pct=15.0,
        mock_price=420.0,
        agent_stances={
            "apollo": Stance.AGREE,
            "hermes": Stance.AGREE,
            "nyx":    Stance.AGREE,
            "vesta":  Stance.AGREE,
        },
    ),
    # ── 2. NYX dissents with contrarian flag ──────────────────────────────────
    "nyx_dissents": ScenarioDef(
        name="nyx_dissents",
        seed=1002,
        ticker="MSFT",
        asset_class=AssetClass.OPTION,
        strategy_type=StrategyType.CSP,
        conviction_score=75,
        proposed_size_pct=15.0,
        mock_price=420.0,
        agent_stances={
            "apollo": Stance.AGREE,
            "hermes": Stance.AGREE,
            "nyx":    Stance.DISAGREE,
            "vesta":  Stance.AGREE,
        },
        contrarian_agents=frozenset({"nyx"}),
    ),
    # ── 3. Deep disagreement — split vote ────────────────────────────────────
    "deep_disagreement": ScenarioDef(
        name="deep_disagreement",
        seed=1003,
        ticker="SPY",
        asset_class=AssetClass.OPTION,
        strategy_type=StrategyType.IRON_CONDOR,
        conviction_score=62,
        proposed_size_pct=10.0,
        mock_price=510.0,
        agent_stances={
            "apollo": Stance.AGREE,
            "hermes": Stance.DISAGREE,
            "nyx":    Stance.DISAGREE,
            "vesta":  Stance.AGREE,
        },
    ),
    # ── 4. Consensus reached but ATLAS blocks ────────────────────────────────
    "atlas_blocks": ScenarioDef(
        name="atlas_blocks",
        seed=1004,
        ticker="NVDA",
        asset_class=AssetClass.OPTION,
        strategy_type=StrategyType.CREDIT_SPREAD,
        conviction_score=80,
        proposed_size_pct=20.0,
        mock_price=875.0,
        agent_stances={
            "apollo": Stance.AGREE,
            "hermes": Stance.AGREE,
            "nyx":    Stance.AGREE,
            "vesta":  Stance.AGREE,
        },
        atlas_block=True,
        atlas_block_reason="Tech sector concentration would exceed 45% limit post-trade",
        buying_power_used_pct=78.5,
    ),
    # ── 5. All neutral but ATHENA conviction ≥ 90 ────────────────────────────
    "high_conviction_solo": ScenarioDef(
        name="high_conviction_solo",
        seed=1005,
        ticker="AAPL",
        asset_class=AssetClass.OPTION,
        strategy_type=StrategyType.CSP,
        conviction_score=92,
        proposed_size_pct=15.0,
        mock_price=195.0,
        agent_stances={
            "apollo": Stance.NEUTRAL,
            "hermes": Stance.NEUTRAL,
            "nyx":    Stance.NEUTRAL,
            "vesta":  Stance.NEUTRAL,
        },
    ),
}
