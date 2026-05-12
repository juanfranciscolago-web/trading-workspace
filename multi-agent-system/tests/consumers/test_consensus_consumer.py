"""
Unit tests for ConsensusConsumer — no DB, no Redis.
12 tests. Verifica: subscribe to CRITIQUES, DB lookup of proposal,
evaluate invocation with N=1 critique, decision persistence + status update,
publish to DECISIONS, order constraints, error propagation.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from multi_agent.communication.enums import (
    AgentId,
    AssetClass,
    ConsensusType,
    DecisionOutcome,
    Direction,
    OptionType,
    Stance,
    StrategyType,
)
from multi_agent.communication.message_bus import AgentChannels, ConsumerGroups
from multi_agent.communication.schemas import (
    ConsensusState,
    CritiqueArgument,
    CritiqueMessage,
    DataSignature,
    DecisionMessage,
    OptionLeg,
    ProposalMessage,
    Thesis,
    TradeDetails,
    TradeSizing,
    TradeStructure,
)
from multi_agent.consumers import ConsensusConsumer
from multi_agent.consumers.consensus_consumer import CONSUMER_NAME, MAX_RETRIES


# ── Test doubles ──────────────────────────────────────────────────────────────

class SpyBus:
    def __init__(self):
        self.subscriptions: list[dict] = []
        self.published: list[tuple] = []

    def subscribe(self, channel, consumer_group, consumer_name, handler, max_retries=None):
        self.subscriptions.append({
            "channel": channel,
            "consumer_group": consumer_group,
            "consumer_name": consumer_name,
            "handler": handler,
            "max_retries": max_retries,
        })

    def publish(self, channel, message):
        self.published.append((channel, message))


class SpyRepo:
    """Test double. Pass a proposal to simulate "found in DB"; None to simulate
    "not found" (stale critique scenario)."""

    def __init__(self, proposal: ProposalMessage | None = None):
        self.decisions: list = []
        self.status_updates: list[tuple] = []
        self._proposal_full_payload = (
            proposal.model_dump(mode="json") if proposal else None
        )

    def save_decision(self, msg):
        self.decisions.append(msg)

    def update_proposal_status(self, correlation_id, status):
        self.status_updates.append((correlation_id, status))

    def get_proposal_by_correlation_id(self, correlation_id):
        if self._proposal_full_payload is None:
            return None
        return {"full_payload": self._proposal_full_payload}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_proposal(correlation_id: UUID | None = None) -> ProposalMessage:
    return ProposalMessage(
        correlation_id=correlation_id or uuid4(),
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
            premise="x", mechanism="x", key_data_points=["x"],
            invalidation="x", target="x",
            time_horizon_days=45, expected_holding_period_days=22,
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
            data_timestamp=datetime(2026, 5, 12, 12, 0, tzinfo=timezone.utc),
            model_version="test",
        ),
    )


def _make_critique(correlation_id: UUID, parent_message_id: UUID) -> CritiqueMessage:
    return CritiqueMessage(
        correlation_id=correlation_id,
        agent_id=AgentId.APOLLO,
        parent_message_id=parent_message_id,
        stance=Stance.AGREE,
        argument=CritiqueArgument(
            summary="macro tailwind",
            concern="watch FOMC",
            data_that_would_change_my_mind="VIX > 25",
        ),
        veto_request=False,
        contrarian_flag_raised=False,
    )


def _make_decision(correlation_id: UUID, parent_message_id: UUID) -> DecisionMessage:
    """Canonical APPROVED/UNANIMOUS decision returned by the mocked
    consensus.evaluate."""
    return DecisionMessage(
        correlation_id=correlation_id,
        agent_id=AgentId.ATLAS,
        parent_message_id=parent_message_id,
        outcome=DecisionOutcome.APPROVED,
        consensus_state=ConsensusState(
            agree=[AgentId.APOLLO],
            consensus_type=ConsensusType.UNANIMOUS,
        ),
    )


def _make_consumer(
    bus: SpyBus | None = None,
    repo: SpyRepo | None = None,
) -> tuple[ConsensusConsumer, SpyBus, SpyRepo]:
    bus = bus or SpyBus()
    repo = repo or SpyRepo()
    consumer = ConsensusConsumer(bus=bus, repo=repo)
    return consumer, bus, repo


def _patch_evaluate(monkeypatch, return_value=None, side_effect=None) -> MagicMock:
    """Monkeypatch consensus.evaluate in the consensus_consumer module."""
    import multi_agent.consumers.consensus_consumer as cc_module
    spy = MagicMock(return_value=return_value, side_effect=side_effect)
    monkeypatch.setattr(cc_module.consensus, "evaluate", spy)
    return spy


# ── Tests: subscribe / start ──────────────────────────────────────────────────

class TestConsensusConsumerSubscribe:
    def test_start_subscribes_to_critiques_channel(self):
        consumer, bus, _ = _make_consumer()
        consumer.start()
        assert len(bus.subscriptions) == 1
        assert bus.subscriptions[0]["channel"] == AgentChannels.CRITIQUES

    def test_start_uses_correct_consumer_group_consensus_engine(self):
        consumer, bus, _ = _make_consumer()
        consumer.start()
        assert bus.subscriptions[0]["consumer_group"] == ConsumerGroups.CONSENSUS_ENGINE
        assert bus.subscriptions[0]["consumer_name"] == CONSUMER_NAME

    def test_start_uses_max_retries_2(self):
        consumer, bus, _ = _make_consumer()
        consumer.start()
        assert bus.subscriptions[0]["max_retries"] == MAX_RETRIES
        assert MAX_RETRIES == 2


# ── Tests: handler ────────────────────────────────────────────────────────────

class TestConsensusConsumerHandler:

    def test_handle_message_evaluates_and_publishes_happy_path(self, monkeypatch):
        """End-to-end: 1 decision saved, status='decided', 1 publish to DECISIONS."""
        proposal = _make_proposal()
        critique = _make_critique(proposal.correlation_id, proposal.message_id)
        decision = _make_decision(proposal.correlation_id, proposal.message_id)
        _patch_evaluate(monkeypatch, return_value=decision)

        repo = SpyRepo(proposal=proposal)
        consumer, bus, _ = _make_consumer(repo=repo)
        consumer._handle_message(critique)

        assert len(repo.decisions) == 1
        assert repo.decisions[0] is decision
        assert len(bus.published) == 1
        channel, msg = bus.published[0]
        assert channel == AgentChannels.DECISIONS
        assert msg is decision

    def test_handle_message_updates_proposal_status_to_decided(self, monkeypatch):
        proposal = _make_proposal()
        critique = _make_critique(proposal.correlation_id, proposal.message_id)
        _patch_evaluate(
            monkeypatch,
            return_value=_make_decision(proposal.correlation_id, proposal.message_id),
        )
        repo = SpyRepo(proposal=proposal)
        consumer, _, _ = _make_consumer(repo=repo)
        consumer._handle_message(critique)

        assert len(repo.status_updates) == 1
        corr, status = repo.status_updates[0]
        assert corr == proposal.correlation_id
        assert status == "decided"

    def test_handle_message_ignores_non_critique_messages(self):
        consumer, bus, repo = _make_consumer()
        consumer._handle_message("not a CritiqueMessage")
        assert len(bus.published) == 0
        assert len(repo.decisions) == 0
        assert len(repo.status_updates) == 0

    def test_handle_message_proposal_not_found_logs_and_returns(self, monkeypatch):
        """Stale critique from DLQ: proposal missing in DB → log warning + return.
        No evaluate, no save, no publish, no status update."""
        critique = _make_critique(uuid4(), uuid4())
        spy = _patch_evaluate(monkeypatch, return_value=None)
        repo = SpyRepo(proposal=None)  # simulates DB miss
        consumer, bus, _ = _make_consumer(repo=repo)
        consumer._handle_message(critique)

        spy.assert_not_called()
        assert len(repo.decisions) == 0
        assert len(repo.status_updates) == 0
        assert len(bus.published) == 0

    def test_handle_message_calls_evaluate_with_proposal_and_single_critique(self, monkeypatch):
        """Sprint 4 N=1: evaluate called with exactly 1 critique in the list.
        Proposal arg is reconstructed from DB (full_payload)."""
        proposal = _make_proposal()
        critique = _make_critique(proposal.correlation_id, proposal.message_id)
        decision = _make_decision(proposal.correlation_id, proposal.message_id)
        spy = _patch_evaluate(monkeypatch, return_value=decision)

        repo = SpyRepo(proposal=proposal)
        consumer, _, _ = _make_consumer(repo=repo)
        consumer._handle_message(critique)

        spy.assert_called_once()
        kwargs = spy.call_args.kwargs
        assert kwargs["correlation_id"] == proposal.correlation_id
        assert isinstance(kwargs["proposal"], ProposalMessage)
        assert kwargs["proposal"].correlation_id == proposal.correlation_id
        assert len(kwargs["critiques"]) == 1
        assert kwargs["critiques"][0] is critique

    def test_handle_message_save_decision_before_status_update(self, monkeypatch):
        """Order: persist decision first, then mark status. If status update
        fails, decision is in DB recoverable."""
        proposal = _make_proposal()
        critique = _make_critique(proposal.correlation_id, proposal.message_id)
        _patch_evaluate(
            monkeypatch,
            return_value=_make_decision(proposal.correlation_id, proposal.message_id),
        )
        repo = SpyRepo(proposal=proposal)
        call_order: list[str] = []

        original_save = repo.save_decision
        def tracked_save(msg):
            call_order.append("save_decision")
            original_save(msg)
        repo.save_decision = tracked_save

        original_update = repo.update_proposal_status
        def tracked_update(corr, status):
            call_order.append("status_update")
            original_update(corr, status)
        repo.update_proposal_status = tracked_update

        consumer, _, _ = _make_consumer(repo=repo)
        consumer._handle_message(critique)

        assert call_order.index("save_decision") < call_order.index("status_update")

    def test_handle_message_save_before_publish(self, monkeypatch):
        """Order: save_decision must complete before publish so a Redis
        failure leaves the decision in DB recoverable."""
        proposal = _make_proposal()
        critique = _make_critique(proposal.correlation_id, proposal.message_id)
        _patch_evaluate(
            monkeypatch,
            return_value=_make_decision(proposal.correlation_id, proposal.message_id),
        )
        repo = SpyRepo(proposal=proposal)
        bus = SpyBus()
        call_order: list[str] = []

        original_save = repo.save_decision
        def tracked_save(msg):
            call_order.append("save_decision")
            original_save(msg)
        repo.save_decision = tracked_save

        original_publish = bus.publish
        def tracked_publish(channel, message):
            call_order.append("publish")
            original_publish(channel, message)
        bus.publish = tracked_publish

        consumer, _, _ = _make_consumer(bus=bus, repo=repo)
        consumer._handle_message(critique)

        assert call_order.index("save_decision") < call_order.index("publish")

    def test_handle_message_consensus_failure_propagates(self, monkeypatch):
        """K3: handler exception bubbles to bus → retries → DLQ. Rare since
        consensus.evaluate is pure, but ensures no silent swallow if a future
        change introduces a failure mode."""
        proposal = _make_proposal()
        critique = _make_critique(proposal.correlation_id, proposal.message_id)
        _patch_evaluate(monkeypatch, side_effect=RuntimeError("consensus boom"))
        repo = SpyRepo(proposal=proposal)
        consumer, bus, _ = _make_consumer(repo=repo)

        with pytest.raises(RuntimeError, match="consensus boom"):
            consumer._handle_message(critique)

        # Consensus raised before save/status/publish.
        assert len(repo.decisions) == 0
        assert len(repo.status_updates) == 0
        assert len(bus.published) == 0


# ── Tests: build factory ──────────────────────────────────────────────────────

class TestConsensusConsumerBuild:
    def test_build_factory_no_claude_router_needed(self):
        """ConsensusConsumer.build takes only bus + repo (consensus.evaluate
        is a pure function, no LLM dependency)."""
        bus = SpyBus()
        repo = SpyRepo()
        consumer = ConsensusConsumer.build(bus=bus, repo=repo)
        assert isinstance(consumer, ConsensusConsumer)
        assert consumer._bus is bus
        assert consumer._repo is repo
