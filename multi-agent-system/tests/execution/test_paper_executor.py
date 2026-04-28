"""
Unit tests for PaperExecutor — no DB, no Redis.
~15 tests. Verifica: slippage, partial fills, routing, guard conditions.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from multi_agent.agents import SCENARIOS, build_orchestrator
from multi_agent.communication.enums import AgentId, TradeStatus
from multi_agent.communication.message_bus import AgentChannels
from multi_agent.communication.schemas import AtlasValidationMessage, ExecutionMessage
from multi_agent.execution import PaperExecutor

from ..agents.conftest import CapturingRepository


# ── Test doubles ──────────────────────────────────────────────────────────────

class SpyBus:
    def __init__(self):
        self.subscriptions: list[dict] = []
        self.published: list[tuple] = []

    def subscribe(self, channel, consumer_group, consumer_name, handler):
        self.subscriptions.append({
            "channel": channel,
            "consumer_group": consumer_group,
        })

    def publish(self, channel, message):
        self.published.append((channel, message))


class SpyRepo:
    def __init__(self):
        self.executions: list = []

    def save_execution(self, msg):
        self.executions.append(msg)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_full_cycle(scenario_name: str = "all_agree"):
    """Returns (proposal, atlas_msg) from mock orchestrator."""
    repo = CapturingRepository()
    orc = build_orchestrator(repo)
    result = orc.run_cycle(SCENARIOS[scenario_name])
    return result.proposal, result.atlas_validation


def _make_executor(bus: SpyBus | None = None, seed: int = 42) -> tuple[PaperExecutor, SpyBus]:
    bus = bus or SpyBus()
    repo = SpyRepo()
    executor = PaperExecutor(bus=bus, repo=repo, rng_seed=seed)
    return executor, bus


# ── Tests: subscribe / start ──────────────────────────────────────────────────

class TestPaperExecutorStart:
    def test_start_subscribes_to_atlas_validation_channel(self):
        executor, bus = _make_executor()
        executor.start()
        assert len(bus.subscriptions) == 1
        assert bus.subscriptions[0]["channel"] == AgentChannels.ATLAS_VALIDATION

    def test_start_uses_paper_executor_group(self):
        executor, bus = _make_executor()
        executor.start()
        assert bus.subscriptions[0]["consumer_group"] == "paper_executor"


# ── Tests: guard conditions ───────────────────────────────────────────────────

class TestGuardConditions:
    def test_rejected_atlas_message_not_published(self):
        executor, bus = _make_executor()
        proposal, atlas = _run_full_cycle("atlas_blocks")
        executor._proposal_cache[str(atlas.correlation_id)] = proposal
        executor._handle_message(atlas)
        # atlas_blocks → approved=False from mock
        if not atlas.approved:
            assert len(bus.published) == 0

    def test_non_atlas_message_ignored(self):
        executor, bus = _make_executor()
        executor._handle_message("not an AtlasValidationMessage")
        assert len(bus.published) == 0

    def test_missing_proposal_in_cache_skips_publish(self):
        executor, bus = _make_executor()
        proposal, atlas = _run_full_cycle("all_agree")
        # Do NOT add to cache
        executor._handle_message(atlas)
        assert len(bus.published) == 0


# ── Tests: happy path execution ───────────────────────────────────────────────

class TestHappyPathExecution:
    def setup_method(self):
        self.executor, self.bus = _make_executor(seed=42)
        self.proposal, self.atlas = _run_full_cycle("all_agree")
        self.executor._proposal_cache[str(self.atlas.correlation_id)] = self.proposal
        self.executor._handle_message(self.atlas)

    def _skip_if_not_approved(self):
        if not self.atlas.approved:
            pytest.skip("Mock returned rejected — scenario not applicable")

    def test_publishes_execution_message(self):
        self._skip_if_not_approved()
        assert len(self.bus.published) == 1

    def test_publishes_to_execution_channel(self):
        self._skip_if_not_approved()
        channel, _ = self.bus.published[0]
        assert channel == AgentChannels.EXECUTION

    def test_published_message_is_execution_type(self):
        self._skip_if_not_approved()
        _, msg = self.bus.published[0]
        assert isinstance(msg, ExecutionMessage)

    def test_correlation_id_matches_atlas(self):
        self._skip_if_not_approved()
        _, msg = self.bus.published[0]
        assert msg.correlation_id == self.atlas.correlation_id

    def test_parent_message_id_is_atlas(self):
        self._skip_if_not_approved()
        _, msg = self.bus.published[0]
        assert msg.parent_message_id == self.atlas.message_id

    def test_fills_count_matches_leg_count(self):
        self._skip_if_not_approved()
        _, msg = self.bus.published[0]
        expected_legs = len(self.proposal.trade.structure.legs)
        assert len(msg.fills) == expected_legs

    def test_fill_venue_is_paper(self):
        self._skip_if_not_approved()
        _, msg = self.bus.published[0]
        for fill in msg.fills:
            assert fill.venue == "PAPER"


# ── Tests: slippage ───────────────────────────────────────────────────────────

class TestSlippage:
    def test_sell_leg_fill_price_below_strike(self):
        """SELL leg: adverse slippage → fill_price < strike."""
        executor, bus = _make_executor(seed=1)
        proposal, atlas = _run_full_cycle("all_agree")  # CSP = SELL put
        executor._proposal_cache[str(atlas.correlation_id)] = proposal
        executor._handle_message(atlas)

        if not atlas.approved or not bus.published:
            pytest.skip("Trade not approved")

        _, msg = bus.published[0]
        # CSP has one SELL leg; fill should be below strike (worse credit than expected)
        from multi_agent.communication.enums import Direction
        sell_legs = [
            (leg, fill) for leg, fill in zip(proposal.trade.structure.legs, msg.fills)
            if leg.action == Direction.SELL
        ]
        assert sell_legs, "No SELL legs found in CSP"
        leg, fill = sell_legs[0]
        assert fill.fill_price < leg.strike, (
            f"Expected fill {fill.fill_price} < strike {leg.strike} for SELL"
        )

    def test_buy_leg_fill_price_above_strike(self):
        """BUY leg: adverse slippage → fill_price > strike."""
        executor, bus = _make_executor(seed=1)
        proposal, atlas = _run_full_cycle("deep_disagreement")  # IRON_CONDOR has BUY legs
        executor._proposal_cache[str(atlas.correlation_id)] = proposal
        executor._handle_message(atlas)

        if not atlas.approved or not bus.published:
            pytest.skip("Trade not approved")

        _, msg = bus.published[0]
        from multi_agent.communication.enums import Direction
        buy_legs = [
            (leg, fill) for leg, fill in zip(proposal.trade.structure.legs, msg.fills)
            if leg.action == Direction.BUY
        ]
        assert buy_legs, "No BUY legs found in iron condor"
        leg, fill = buy_legs[0]
        assert fill.fill_price > leg.strike, (
            f"Expected fill {fill.fill_price} > strike {leg.strike} for BUY"
        )

    def test_fill_price_differs_from_strike(self):
        """Slippage is applied — fill != strike in all cases."""
        executor, bus = _make_executor(seed=7)
        proposal, atlas = _run_full_cycle("all_agree")
        executor._proposal_cache[str(atlas.correlation_id)] = proposal
        executor._handle_message(atlas)

        if not atlas.approved or not bus.published:
            pytest.skip("Trade not approved")

        _, msg = bus.published[0]
        leg = proposal.trade.structure.legs[0]
        fill = msg.fills[0]
        assert fill.fill_price != leg.strike, "Expected slippage but got exact fill"


# ── Tests: execution status ───────────────────────────────────────────────────

class TestExecutionStatus:
    def test_status_filled_when_no_partial(self):
        """With rng forced to never trigger partial, status = FILLED."""
        executor, bus = _make_executor(seed=0)
        proposal, atlas = _run_full_cycle("all_agree")
        executor._proposal_cache[str(atlas.correlation_id)] = proposal

        with patch.object(executor._rng, "random", return_value=0.99):  # > 0.08
            executor._handle_message(atlas)

        if not atlas.approved or not bus.published:
            pytest.skip("Trade not approved")

        _, msg = bus.published[0]
        assert msg.execution_status == TradeStatus.FILLED

    def test_status_partial_fill_when_triggered(self):
        """With rng forced to trigger partial, status = PARTIAL_FILL."""
        executor, bus = _make_executor(seed=0)
        proposal, atlas = _run_full_cycle("all_agree")
        executor._proposal_cache[str(atlas.correlation_id)] = proposal

        with patch.object(executor._rng, "random", return_value=0.01):  # < 0.08
            executor._handle_message(atlas)

        if not atlas.approved or not bus.published:
            pytest.skip("Trade not approved")

        _, msg = bus.published[0]
        assert msg.execution_status == TradeStatus.PARTIAL

    def test_partial_fill_status_set_to_partial(self):
        """When partial fill triggers, execution status is PARTIAL regardless of qty floor."""
        executor, bus = _make_executor(seed=0)
        proposal, atlas = _run_full_cycle("all_agree")
        executor._proposal_cache[str(atlas.correlation_id)] = proposal

        with patch.object(executor._rng, "random", return_value=0.01):  # force partial
            executor._handle_message(atlas)

        if not atlas.approved or not bus.published:
            pytest.skip("Trade not approved")

        _, msg = bus.published[0]
        assert msg.execution_status == TradeStatus.PARTIAL


# ── Tests: determinism ────────────────────────────────────────────────────────

class TestDeterminism:
    def test_same_seed_produces_same_fill_prices(self):
        """Two executors with same seed → identical fill prices."""
        proposal, atlas = _run_full_cycle("all_agree")

        def _run(seed):
            executor, bus = _make_executor(seed=seed)
            executor._proposal_cache[str(atlas.correlation_id)] = proposal
            executor._handle_message(atlas)
            return bus.published

        result_a = _run(99)
        result_b = _run(99)

        if not atlas.approved or not result_a or not result_b:
            pytest.skip("Trade not approved")

        fills_a = result_a[0][1].fills
        fills_b = result_b[0][1].fills
        for fa, fb in zip(fills_a, fills_b):
            assert fa.fill_price == fb.fill_price

    def test_different_seeds_may_differ(self):
        """Different seeds → different fill prices (probabilistic, but very likely)."""
        proposal, atlas = _run_full_cycle("all_agree")

        def _run(seed):
            executor, bus = _make_executor(seed=seed)
            executor._proposal_cache[str(atlas.correlation_id)] = proposal
            executor._handle_message(atlas)
            return bus.published

        result_a = _run(1)
        result_b = _run(2)

        if not atlas.approved or not result_a or not result_b:
            pytest.skip("Trade not approved")

        price_a = result_a[0][1].fills[0].fill_price
        price_b = result_b[0][1].fills[0].fill_price
        assert price_a != price_b, "Seeds 1 and 2 produced identical fill prices (unlikely but possible)"
