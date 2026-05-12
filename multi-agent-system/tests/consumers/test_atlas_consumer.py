"""
Unit tests for AtlasConsumer — no DB, no Redis.
~13 tests. Verifica: subscribe, proposal cache, handle approved, handle rejected, DLQ.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from multi_agent.agents import SCENARIOS, build_orchestrator
from multi_agent.communication.enums import AgentId
from multi_agent.communication.message_bus import AgentChannels, ConsumerGroups
from multi_agent.communication.schemas import AtlasValidationMessage
from multi_agent.consumers import AtlasConsumer
from multi_agent.risk.portfolio_snapshot import PortfolioSnapshot, PositionView, snapshot_hash

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
            "consumer_name": consumer_name,
            "handler": handler,
        })

    def publish(self, channel, message):
        self.published.append((channel, message))


class SpyRepo:
    def __init__(self):
        self.atlas_validations: list = []
        self.atlas_snapshots: list = []
        self.rejected_dlqs: list = []
        self.proposal_status_updates: list = []

    def save_atlas_validation(self, msg):
        self.atlas_validations.append(msg)

    def save_atlas_snapshot(self, **kwargs):
        self.atlas_snapshots.append(kwargs)

    def save_rejected_dlq(self, **kwargs):
        self.rejected_dlqs.append(kwargs)

    def update_proposal_status(self, correlation_id, status):
        # S.5.5: AtlasConsumer transitions proposals.status to 'atlas_validated'
        # or 'rejected' after validation. Record-to-list pattern for assertion.
        self.proposal_status_updates.append((correlation_id, status))

    def get_proposal_by_correlation_id(self, correlation_id):
        # F1 fallback (Sprint 4 B.4.5a): AtlasConsumer falls back to DB
        # lookup on cache miss. SpyRepo simulates a DB miss so cache-miss
        # tests still exercise the fail-closed path.
        return None


class FakeSnapshotBuilder:
    def __init__(self, snapshot: PortfolioSnapshot):
        self._snapshot = snapshot
        self.call_count = 0

    def get(self) -> PortfolioSnapshot:
        self.call_count += 1
        return self._snapshot


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def _make_position(ticker: str, qty: int, price: float) -> PositionView:
    return PositionView(
        ticker=ticker, asset_class="equity", strategy_type=None,
        market_value_usd=Decimal(str(abs(qty) * price)),
        quantity=qty, delta=Decimal(str(abs(qty))),
        vega=Decimal("0"), theta=Decimal("0"),
    )


def _healthy_snapshot() -> PortfolioSnapshot:
    positions = [_make_position("MSFT", 100, 440.0)]
    ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
    sid = snapshot_hash(positions, Decimal("850000"), Decimal("0"), ts)
    return PortfolioSnapshot(
        positions=tuple(positions),
        nav_usd=Decimal("1000000"), cash_usd=Decimal("850000"),
        buying_power_used_pct=16.0, portfolio_beta=0.82, vega_total=-12400.0,
        pnl_daily_usd=Decimal("0"), pnl_daily_pct=0.0,
        pnl_weekly_pct=0.0, pnl_monthly_pct=0.0,
        drawdown_from_peak_pct=-2.1, snapshot_at=ts, snapshot_id=sid,
    )


def _kill_switch_snapshot() -> PortfolioSnapshot:
    """Drawdown at -26% → triggers kill switch (limit = -25%)."""
    positions = [_make_position("MSFT", 100, 440.0)]
    ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
    sid = snapshot_hash(positions, Decimal("600000"), Decimal("-260000"), ts)
    return PortfolioSnapshot(
        positions=tuple(positions),
        nav_usd=Decimal("1000000"), cash_usd=Decimal("600000"),
        buying_power_used_pct=20.0, portfolio_beta=0.82, vega_total=0.0,
        pnl_daily_usd=Decimal("-260000"), pnl_daily_pct=-26.0,
        pnl_weekly_pct=-26.0, pnl_monthly_pct=-26.0,
        drawdown_from_peak_pct=-26.0, snapshot_at=ts, snapshot_id=sid,
    )


# ── Consumer factory ──────────────────────────────────────────────────────────

def _make_consumer(
    bus: SpyBus | None = None,
    repo: SpyRepo | None = None,
    snapshot: PortfolioSnapshot | None = None,
) -> tuple[AtlasConsumer, SpyBus, SpyRepo, FakeSnapshotBuilder]:
    bus = bus or SpyBus()
    repo = repo or SpyRepo()
    snap = snapshot or _healthy_snapshot()
    builder = FakeSnapshotBuilder(snap)
    consumer = AtlasConsumer(bus=bus, repo=repo, snapshot_builder=builder)
    return consumer, bus, repo, builder


def _run_cycle(scenario_name: str = "all_agree"):
    """Returns (proposal, decision) using mock orchestrator."""
    repo = CapturingRepository()
    orc = build_orchestrator(repo)
    result = orc.run_cycle(SCENARIOS[scenario_name])
    return result.proposal, result.decision


# ── Tests: subscribe / start ──────────────────────────────────────────────────

class TestAtlasConsumerStart:
    def test_start_subscribes_to_decisions_channel(self):
        consumer, bus, _, _ = _make_consumer()
        consumer.start()
        assert len(bus.subscriptions) == 1
        assert bus.subscriptions[0]["channel"] == AgentChannels.DECISIONS

    def test_start_uses_atlas_validator_consumer_group(self):
        consumer, bus, _, _ = _make_consumer()
        consumer.start()
        assert bus.subscriptions[0]["consumer_group"] == ConsumerGroups.ATLAS_VALIDATOR


# ── Tests: proposal cache ─────────────────────────────────────────────────────

class TestProposalCache:
    def test_cache_proposal_stores_by_corr_id(self):
        consumer, _, _, _ = _make_consumer()
        proposal, _ = _run_cycle("all_agree")
        consumer.cache_proposal(proposal)
        assert str(proposal.correlation_id) in consumer._proposal_cache

    def test_evict_proposal_removes_from_cache(self):
        consumer, _, _, _ = _make_consumer()
        proposal, _ = _run_cycle("all_agree")
        consumer.cache_proposal(proposal)
        consumer.evict_proposal(proposal.correlation_id)
        assert str(proposal.correlation_id) not in consumer._proposal_cache

    def test_evict_nonexistent_is_safe(self):
        consumer, _, _, _ = _make_consumer()
        consumer.evict_proposal(uuid4())  # must not raise


# ── Tests: handle approved message ───────────────────────────────────────────

class TestHandleApproved:
    def setup_method(self):
        self.consumer, self.bus, self.repo, self.builder = _make_consumer(
            snapshot=_healthy_snapshot(),
        )
        proposal, decision = _run_cycle("all_agree")
        self.proposal = proposal
        self.consumer.cache_proposal(proposal)
        self.consumer._handle_message(decision)

    def test_publishes_exactly_one_message(self):
        assert len(self.bus.published) == 1

    def test_publishes_to_atlas_validation_channel(self):
        channel, _ = self.bus.published[0]
        assert channel == AgentChannels.ATLAS_VALIDATION

    def test_published_message_is_atlas_validation_type(self):
        _, msg = self.bus.published[0]
        assert isinstance(msg, AtlasValidationMessage)

    def test_published_message_agent_id_is_atlas(self):
        _, msg = self.bus.published[0]
        assert msg.agent_id == AgentId.ATLAS

    def test_correlation_id_matches_proposal(self):
        _, msg = self.bus.published[0]
        assert msg.correlation_id == self.proposal.correlation_id

    def test_saves_atlas_validation_to_repo(self):
        assert len(self.repo.atlas_validations) == 1

    def test_saves_atlas_snapshot_to_repo(self):
        assert len(self.repo.atlas_snapshots) == 1

    def test_snapshot_builder_called_once(self):
        assert self.builder.call_count == 1

    def test_no_dlq_entry_for_approved_trade(self):
        _, msg = self.bus.published[0]
        if msg.approved:
            assert len(self.repo.rejected_dlqs) == 0

    def test_updates_status_to_atlas_validated(self):
        """S.5.5: AtlasConsumer transitions proposals.status to
        'atlas_validated' after approving a trade."""
        assert len(self.repo.proposal_status_updates) == 1
        _, status = self.repo.proposal_status_updates[0]
        assert status == 'atlas_validated'


# ── Tests: handle rejected message ───────────────────────────────────────────

class TestHandleRejected:
    def setup_method(self):
        # Kill-switch snapshot → atlas_validate returns approved=False
        self.consumer, self.bus, self.repo, _ = _make_consumer(
            snapshot=_kill_switch_snapshot(),
        )
        proposal, decision = _run_cycle("all_agree")
        self.consumer.cache_proposal(proposal)
        self.consumer._handle_message(decision)

    def test_publishes_rejected_atlas_message(self):
        assert len(self.bus.published) == 1
        _, msg = self.bus.published[0]
        assert not msg.approved

    def test_rejected_message_has_zero_executed_size(self):
        _, msg = self.bus.published[0]
        assert msg.executed_size == Decimal("0")

    def test_rejected_trade_writes_dlq_entry(self):
        assert len(self.repo.rejected_dlqs) == 1

    def test_updates_status_to_rejected(self):
        """S.5.5: AtlasConsumer transitions proposals.status to 'rejected'
        when atlas_validate returns approved=False (kill switch path)."""
        assert len(self.repo.proposal_status_updates) == 1
        _, status = self.repo.proposal_status_updates[0]
        assert status == 'rejected'


# ── Tests: guard conditions ───────────────────────────────────────────────────

class TestGuardConditions:
    def test_missing_proposal_skips_publish(self):
        consumer, bus, repo, _ = _make_consumer()
        _, decision = _run_cycle("all_agree")
        consumer._handle_message(decision)  # no cached proposal
        assert len(bus.published) == 0
        assert len(repo.atlas_validations) == 0

    def test_non_decision_message_ignored(self):
        consumer, bus, repo, _ = _make_consumer()
        consumer._handle_message("not a DecisionMessage")
        assert len(bus.published) == 0
        assert len(repo.atlas_validations) == 0
