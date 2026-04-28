#!/usr/bin/env python
"""
run_cycle.py — Drive one trade cycle through the mock agent system.

Usage:
    python run_cycle.py --scenario all_agree
    python run_cycle.py --scenario nyx_dissents --seed 9999
    python run_cycle.py --scenario atlas_blocks

Available scenarios: all_agree, nyx_dissents, deep_disagreement,
                     atlas_blocks, high_conviction_solo

If DATABASE_URL is set, messages are also persisted to PostgreSQL.
Without DATABASE_URL, a capturing repository is used (no DB required).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Ensure src/ is importable when run from the multi-agent-system directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from multi_agent.agents import SCENARIOS, build_orchestrator
from multi_agent.agents.base import CycleResult
from multi_agent.communication.enums import AtlasDecision, DecisionOutcome

logging.basicConfig(level=logging.WARNING)

# ── Capturing repository (no DB) ──────────────────────────────────────────────


class CapturingRepository:
    """Stores all messages in memory; used when DATABASE_URL is absent."""

    def __init__(self) -> None:
        self.saved: list = []

    def save_proposal(self, msg, **_): self.saved.append(msg)
    def save_critique(self, msg, **_): self.saved.append(msg)
    def save_decision(self, msg, **_): self.saved.append(msg)
    def save_atlas_validation(self, msg, **_): self.saved.append(msg)
    def log_llm_cost(self, **_): pass


# ── Formatting helpers ────────────────────────────────────────────────────────


def _outcome_icon(outcome: DecisionOutcome) -> str:
    return {
        DecisionOutcome.APPROVED: "✓ APPROVED",
        DecisionOutcome.APPROVED_WITH_CONDITIONS: "⚡ APPROVED WITH CONDITIONS",
        DecisionOutcome.REJECTED: "✗ REJECTED",
        DecisionOutcome.DEFERRED: "⏸ DEFERRED",
        DecisionOutcome.BLOCKED: "🚫 BLOCKED",
    }.get(outcome, str(outcome))


def _atlas_icon(decision: AtlasDecision) -> str:
    return {
        AtlasDecision.APPROVED: "✓ APPROVED",
        AtlasDecision.APPROVED_WITH_CONDITIONS: "⚡ APPROVED WITH CONDITIONS",
        AtlasDecision.BLOCKED: "🚫 BLOCKED",
    }.get(decision, str(decision))


def print_result(result: CycleResult) -> None:
    p = result.proposal
    d = result.decision
    a = result.atlas_validation

    print(f"\n{'='*60}")
    print(f"  CYCLE: {p.trade.ticker}  [{p.trade.strategy_type.value}]")
    print(f"  corr_id: {result.correlation_id}")
    print(f"{'='*60}")

    print(f"\n[ATHENA] Proposal")
    print(f"  conviction: {p.conviction_score}/100")
    print(f"  proposed:   {p.sizing.proposed_size_pct_portfolio:.1f}%  "
          f"(${float(p.sizing.proposed_size_usd):,.0f})")
    print(f"  thesis:     {p.thesis.premise[:80]}...")

    print(f"\n[CRITICS]")
    for c in result.critiques:
        flag = " [CONTRARIAN]" if c.contrarian_flag_raised else ""
        print(f"  {c.agent_id.value:<8} {c.stance.value}{flag}")
        print(f"           {c.argument.summary[:72]}")

    cs = d.consensus_state
    agree_names = [a.value for a in cs.agree]
    disagree_names = [a.value for a in cs.disagree]
    neutral_names = [a.value for a in cs.neutral]
    print(f"\n[CONSENSUS] {cs.consensus_type.value}")
    if agree_names:
        print(f"  agree:    {', '.join(agree_names)}")
    if disagree_names:
        print(f"  disagree: {', '.join(disagree_names)}")
    if neutral_names:
        print(f"  neutral:  {', '.join(neutral_names)}")

    print(f"\n[DECISION] {_outcome_icon(d.outcome)}")
    if d.size_modulation:
        sm = d.size_modulation
        print(f"  size:     {sm.original_size_pct:.1f}% → {sm.approved_size_pct:.1f}%")
        print(f"  reason:   {sm.reduction_reason}")
    for cond in d.conditions:
        print(f"  cond:     {cond}")

    print(f"\n[ATLAS]  {_atlas_icon(a.decision)}  risk_mode={a.risk_mode.value}")
    pi = a.portfolio_impact
    print(f"  buying power used: {pi.current_state.buying_power_used_pct:.1f}% "
          f"→ {pi.post_trade_state.buying_power_used_pct:.1f}%")
    print(f"  tech concentration: {pi.current_state.tech_concentration_pct:.1f}% "
          f"→ {pi.post_trade_state.tech_concentration_pct:.1f}%")
    for mod in a.modulations_applied:
        print(f"  note:    {mod}")

    # Final verdict
    print(f"\n{'─'*60}")
    if a.decision == AtlasDecision.BLOCKED:
        print("  FINAL: TRADE BLOCKED by ATLAS")
    elif d.outcome in (DecisionOutcome.REJECTED, DecisionOutcome.DEFERRED):
        print(f"  FINAL: TRADE {d.outcome.value} — not sent to execution")
    else:
        final_pct = (
            d.size_modulation.approved_size_pct
            if d.size_modulation
            else p.sizing.proposed_size_pct_portfolio
        )
        print(f"  FINAL: PROCEED TO EXECUTION at {final_pct:.1f}% portfolio")
    print(f"{'='*60}\n")


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one mock trade cycle")
    parser.add_argument(
        "--scenario",
        choices=list(SCENARIOS),
        default="all_agree",
        help="Named scenario to run",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed (overrides scenario default)",
    )
    args = parser.parse_args()

    scenario = SCENARIOS[args.scenario]

    # Use real DB repo if DATABASE_URL is set, else capturing
    repo: object
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        try:
            from shared_core.storage.postgres_pool import PostgresPool
            from multi_agent.persistence import MessageRepository
            pool = PostgresPool(dsn=db_url)
            repo = MessageRepository(pool)
            print(f"[DB] Persisting to PostgreSQL at {db_url.split('@')[-1]}")
        except Exception as exc:
            print(f"[DB] Could not connect ({exc}); using in-memory repo")
            repo = CapturingRepository()
    else:
        repo = CapturingRepository()

    orchestrator = build_orchestrator(repo)
    result = orchestrator.run_cycle(scenario, seed=args.seed)
    print_result(result)


if __name__ == "__main__":
    main()
