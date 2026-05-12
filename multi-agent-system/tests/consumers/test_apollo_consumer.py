"""
Unit tests for ApolloConsumer — no DB, no Redis, no LLM.
12 tests. Verifica: subscribe to PROPOSALS, status transition, LLM call args,
critique persistence, publish to CRITIQUES, order constraints, error propagation.
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
    Direction,
    OptionType,
    Stance,
    StrategyType,
)
from multi_agent.communication.message_bus import AgentChannels, ConsumerGroups
from multi_agent.communication.schemas import (
    CritiqueArgument,
    CritiqueMessage,
    DataSignature,
    OptionLeg,
    ProposalMessage,
    Thesis,
    TradeDetails,
    TradeSizing,
    TradeStructure,
)
from multi_agent.consumers import ApolloConsumer
from multi_agent.consumers.apollo_consumer import CONSUMER_NAME, MAX_RETRIES


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
    def __init__(self):
        self.critiques: list = []
        self.status_updates: list[tuple] = []

    def save_critique(self, msg):
        self.critiques.append(msg)

    def update_proposal_status(self, correlation_id, status):
        self.status_updates.append((correlation_id, status))


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


def _make_consumer(
    bus: SpyBus | None = None,
    repo: SpyRepo | None = None,
    apollo_agent: MagicMock | None = None,
    data_layer: MagicMock | None = None,
) -> tuple[ApolloConsumer, SpyBus, SpyRepo, MagicMock, MagicMock]:
    bus = bus or SpyBus()
    repo = repo or SpyRepo()
    apollo_agent = apollo_agent or MagicMock()
    data_layer = data_layer or MagicMock()
    consumer = ApolloConsumer(
        bus=bus, repo=repo, apollo_agent=apollo_agent, data_layer=data_layer,
    )
    return consumer, bus, repo, apollo_agent, data_layer


# ── Tests: subscribe / start ──────────────────────────────────────────────────

class TestApolloConsumerSubscribe:
    def test_start_subscribes_to_proposals_channel(self):
        consumer, bus, _, _, _ = _make_consumer()
        consumer.start()
        assert len(bus.subscriptions) == 1
        assert bus.subscriptions[0]["channel"] == AgentChannels.PROPOSALS

    def test_start_uses_correct_consumer_group_critique_engine(self):
        consumer, bus, _, _, _ = _make_consumer()
        consumer.start()
        assert bus.subscriptions[0]["consumer_group"] == ConsumerGroups.CRITIQUE_ENGINE
        assert bus.subscriptions[0]["consumer_name"] == CONSUMER_NAME

    def test_start_uses_max_retries_2(self):
        consumer, bus, _, _, _ = _make_consumer()
        consumer.start()
        assert bus.subscriptions[0]["max_retries"] == MAX_RETRIES
        assert MAX_RETRIES == 2


# ── Tests: handler ────────────────────────────────────────────────────────────

class TestApolloConsumerHandler:

    def _setup_happy_path(self):
        """Build a consumer + run happy-path handle once. Returns context dict
        for assertion in individual tests."""
        proposal = _make_proposal()
        critique = _make_critique(proposal.correlation_id, proposal.message_id)
        apollo_agent = MagicMock()
        apollo_agent.critique_proposal.return_value = critique
        data_layer = MagicMock()
        market_state = MagicMock()
        data_layer.snapshot.return_value = market_state
        consumer, bus, repo, _, _ = _make_consumer(
            apollo_agent=apollo_agent, data_layer=data_layer,
        )
        consumer._handle_message(proposal)
        return {
            "proposal": proposal,
            "critique": critique,
            "bus": bus,
            "repo": repo,
            "apollo_agent": apollo_agent,
            "data_layer": data_layer,
            "market_state": market_state,
        }

    def test_handle_message_critiques_and_publishes_happy_path(self):
        """End-to-end: 1 critique saved, 1 message published to CRITIQUES."""
        ctx = self._setup_happy_path()
        assert len(ctx["repo"].critiques) == 1
        assert ctx["repo"].critiques[0] is ctx["critique"]
        assert len(ctx["bus"].published) == 1
        channel, msg = ctx["bus"].published[0]
        assert channel == AgentChannels.CRITIQUES
        assert msg is ctx["critique"]

    def test_handle_message_updates_proposal_status_to_under_critique(self):
        ctx = self._setup_happy_path()
        assert len(ctx["repo"].status_updates) == 1
        corr, status = ctx["repo"].status_updates[0]
        assert corr == ctx["proposal"].correlation_id
        assert status == "under_critique"

    def test_handle_message_ignores_non_proposal_messages(self):
        consumer, bus, repo, apollo_agent, _ = _make_consumer()
        consumer._handle_message("not a ProposalMessage")
        assert len(bus.published) == 0
        assert len(repo.critiques) == 0
        assert len(repo.status_updates) == 0
        apollo_agent.critique_proposal.assert_not_called()

    def test_handle_message_calls_apollo_with_correct_args(self):
        ctx = self._setup_happy_path()
        ctx["apollo_agent"].critique_proposal.assert_called_once_with(
            proposal=ctx["proposal"],
            market_state=ctx["market_state"],
            correlation_id=ctx["proposal"].correlation_id,
        )

    def test_handle_message_uses_snapshot_from_data_layer(self):
        ctx = self._setup_happy_path()
        ctx["data_layer"].snapshot.assert_called_once()

    def test_handle_message_status_update_before_llm_call(self):
        """Status must update BEFORE LLM call so dashboard polling sees
        'under_critique' during the 5-15s wait. Implementation: track call
        order via side_effect that captures repo state at LLM call time."""
        proposal = _make_proposal()
        repo = SpyRepo()
        call_order: list[str] = []

        # Wrap update_proposal_status to track ordering.
        original_update = repo.update_proposal_status
        def tracked_update(corr, status):
            call_order.append("status_update")
            original_update(corr, status)
        repo.update_proposal_status = tracked_update

        apollo_agent = MagicMock()
        def tracked_apollo(**kwargs):
            call_order.append("apollo_call")
            return _make_critique(proposal.correlation_id, proposal.message_id)
        apollo_agent.critique_proposal.side_effect = tracked_apollo

        consumer, _, _, _, _ = _make_consumer(repo=repo, apollo_agent=apollo_agent)
        consumer._handle_message(proposal)

        assert call_order.index("status_update") < call_order.index("apollo_call")

    def test_handle_message_save_critique_before_publish(self):
        """save_critique must complete before publish so a Redis failure
        leaves the critique in DB recoverable (mirrors B.4.4 endpoint order)."""
        proposal = _make_proposal()
        critique = _make_critique(proposal.correlation_id, proposal.message_id)
        repo = SpyRepo()
        bus = SpyBus()
        call_order: list[str] = []

        original_save = repo.save_critique
        def tracked_save(msg):
            call_order.append("save_critique")
            original_save(msg)
        repo.save_critique = tracked_save

        original_publish = bus.publish
        def tracked_publish(channel, message):
            call_order.append("publish")
            original_publish(channel, message)
        bus.publish = tracked_publish

        apollo_agent = MagicMock()
        apollo_agent.critique_proposal.return_value = critique
        consumer, _, _, _, _ = _make_consumer(bus=bus, repo=repo, apollo_agent=apollo_agent)
        consumer._handle_message(proposal)

        assert call_order.index("save_critique") < call_order.index("publish")

    def test_handle_message_llm_failure_propagates(self):
        """K3: handler exception bubbles to bus → retries → DLQ. Status was
        already updated before the failure (intentional — operator sees
        'under_critique' stuck as the signal to investigate)."""
        proposal = _make_proposal()
        apollo_agent = MagicMock()
        apollo_agent.critique_proposal.side_effect = RuntimeError("LLM timeout")
        consumer, bus, repo, _, _ = _make_consumer(apollo_agent=apollo_agent)

        with pytest.raises(RuntimeError, match="LLM timeout"):
            consumer._handle_message(proposal)

        # Status was updated before failure.
        assert len(repo.status_updates) == 1
        assert repo.status_updates[0][1] == "under_critique"
        # No critique saved, no publish.
        assert len(repo.critiques) == 0
        assert len(bus.published) == 0


# ── Tests: build factory ──────────────────────────────────────────────────────

class TestApolloConsumerBuild:
    def test_build_factory_creates_apollo_agent_from_router(self):
        """Factory wires ClaudeRouter into an ApolloAgent instance."""
        from multi_agent.agents.apollo_agent import ApolloAgent

        bus = SpyBus()
        repo = SpyRepo()
        claude_router = MagicMock()
        data_layer = MagicMock()
        consumer = ApolloConsumer.build(
            bus=bus, repo=repo,
            claude_router=claude_router, data_layer=data_layer,
        )
        assert isinstance(consumer._apollo_agent, ApolloAgent)
        assert consumer._apollo_agent._claude_router is claude_router
        assert consumer._data_layer is data_layer
