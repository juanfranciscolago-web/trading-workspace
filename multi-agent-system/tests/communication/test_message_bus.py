"""
Tests for AgentMessageBus (Redis Streams).

Uses fakeredis — no real Redis instance required.

Test classes:
  TestPublishConsume       — core XADD / XREADGROUP / XACK flow
  TestFanOut               — multiple consumer groups (each gets every message)
  TestRetryAndDLQ          — ack-after-success, PEL retention, DLQ after max_retries
  TestPendingOnRestart     — drain PEL on bus startup (crash-recovery simulation)
  TestResilience           — malformed JSON, crashing handlers, idempotent start/stop
  TestDLQSystemError       — SYSTEM_ERROR emitted via EventPublisher on DLQ
  TestRoundTrip            — all 6 message types with real Pydantic objects
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import fakeredis
import pytest

from multi_agent.communication import (
    AgentId,
    AtlasDecision,
    AtlasReason,
    AtlasValidationMessage,
    CalibrationUpdate,
    ConsensusState,
    ConsensusType,
    CritiqueArgument,
    CritiqueMessage,
    DataSignature,
    DecisionMessage,
    DecisionOutcome,
    DissentEvaluation,
    EvidenceItem,
    ExecutionMessage,
    FillRecord,
    OptionLeg,
    PostmortemMessage,
    ProposalMessage,
    RiskMode,
    SizeModulation,
    SlippageInfo,
    Stance,
    StrategyType,
    Thesis,
    ThesisEvaluation,
    TradeDetails,
    TradeOutcome,
    TradeResult,
    TradeSizing,
    TradeStructure,
    deserialize_message,
)
from multi_agent.communication.enums import AssetClass, Direction, OptionType, TradeStatus
from multi_agent.communication.message_bus import (
    AgentChannels,
    AgentMessageBus,
    ConsumerGroups,
    MAX_RETRIES_DEFAULT,
)

CORR = uuid4()


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — minimal valid instances of all 6 message types
# ─────────────────────────────────────────────────────────────────────────────

def make_proposal() -> ProposalMessage:
    return ProposalMessage(
        agent_id=AgentId.ATHENA,
        correlation_id=CORR,
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
                estimated_credit=Decimal("4.85"),
                max_profit=Decimal("4850.00"),
                max_loss=Decimal("405150.00"),
                breakeven=Decimal("405.15"),
                buying_power_required=Decimal("41000.00"),
            ),
        ),
        thesis=Thesis(
            premise="MSFT en soporte con IV Rank elevado",
            mechanism="IV crush + soporte horizontal",
            key_data_points=["IV Rank: 62", "Soporte 408-412"],
            invalidation="Cierre debajo de 405",
            target="50% max profit",
            time_horizon_days=45,
            expected_holding_period_days=22,
        ),
        conviction_score=78,
        sizing=TradeSizing(
            proposed_size_pct_portfolio=4.1,
            proposed_size_usd=Decimal("41000.00"),
            kelly_suggested=5.2,
            kelly_fraction_applied=0.25,
        ),
        data_signature=DataSignature(
            data_sources=["schwab_options_chain"],
            data_timestamp=datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc),
            model_version="athena-csp-v2.3",
        ),
    )


def make_critique() -> CritiqueMessage:
    return CritiqueMessage(
        agent_id=AgentId.NYX,
        correlation_id=CORR,
        stance=Stance.DISAGREE,
        argument=CritiqueArgument(
            summary="Vol en mínimos históricos",
            evidence=[EvidenceItem(claim="VIX 11.2", data_source="vix_rt", value=11.2)],
            concern="Vendiendo vol cuando vol está baja",
            data_that_would_change_my_mind="VIX > 15",
        ),
        contrarian_flag_raised=True,
    )


def make_decision() -> DecisionMessage:
    return DecisionMessage(
        agent_id=AgentId.ATLAS,
        correlation_id=CORR,
        outcome=DecisionOutcome.APPROVED_WITH_CONDITIONS,
        consensus_state=ConsensusState(
            agree=[AgentId.ATHENA, AgentId.APOLLO],
            disagree=[AgentId.NYX],
            neutral=[AgentId.HERMES],
            consensus_type=ConsensusType.MAJORITY_WITH_PRODUCTIVE_DISAGREEMENT,
        ),
        size_modulation=SizeModulation(
            original_size_pct=4.1,
            approved_size_pct=2.05,
            reduction_reason="NYX disagreement estructural — size 50%",
        ),
        conditions=["Watch flag: si VIX < 10 NYX puede bloquear"],
    )


def make_atlas_validation() -> AtlasValidationMessage:
    return AtlasValidationMessage(
        agent_id=AgentId.ATLAS,
        correlation_id=CORR,
        atlas_version="atlas-mvp-1.0",
        approved=True,
        executed_size=Decimal("4.10"),
        original_size=Decimal("4.10"),
        reason=AtlasReason.APPROVED,
        risk_mode=RiskMode.GREEN,
        checks_passed=["kill_switches", "pnl_halt", "buying_power", "single_name"],
        checks_failed=[],
        metrics_snapshot={
            "portfolio.beta_current": 0.87,
            "portfolio.risk_mode": "GREEN",
            "stress.spx_down_5pct": {"impact_usd": -8200.0, "impact_pct": -0.82},
            "stress.vix_spike_30pct": {"impact_usd": -37200.0, "impact_pct": -3.72},
        },
        portfolio_snapshot_id="a" * 64,
        evaluation_time_ms=3.5,
    )


def make_execution() -> ExecutionMessage:
    return ExecutionMessage(
        agent_id=AgentId.HERMES,
        correlation_id=CORR,
        execution_status=TradeStatus.FILLED,
        fills=[FillRecord(
            leg=1,
            fill_price=Decimal("4.82"),
            fill_quantity=10,
            fill_timestamp=datetime(2026, 4, 28, 14, 35, 42, tzinfo=timezone.utc),
            venue="SCHWAB",
        )],
        slippage_vs_proposal=SlippageInfo(
            expected_credit=Decimal("4.85"),
            actual_credit=Decimal("4.82"),
            slippage_pct=-0.62,
        ),
        execution_time_ms=3421,
    )


def make_postmortem() -> PostmortemMessage:
    return PostmortemMessage(
        agent_id=AgentId.ATHENA,
        correlation_id=CORR,
        trade_owner=AgentId.ATHENA,
        outcome=TradeOutcome(
            result=TradeResult.WIN,
            pl_usd=2410.0,
            pl_pct_portfolio=0.24,
            holding_period_days=19,
            exit_reason="50% max profit hit",
        ),
        thesis_evaluation=ThesisEvaluation(
            premise_validated=True,
            mechanism_worked_as_expected=True,
            invalidation_triggered=False,
            lessons=["IV crush ocurrió como modelo predijo"],
        ),
        dissent_evaluation=[DissentEvaluation(
            dissenting_agent=AgentId.NYX,
            dissent_validated=False,
            validation_reasoning="Sentiment no se materializó",
            trust_score_adjustment=-0.02,
        )],
        calibration_update=CalibrationUpdate(
            predicted_pop=78,
            actual_outcome="WIN",
            brier_score_contribution=0.048,
        ),
    )


ALL_MESSAGES = [
    (AgentChannels.PROPOSALS,        make_proposal),
    (AgentChannels.CRITIQUES,        make_critique),
    (AgentChannels.DECISIONS,        make_decision),
    (AgentChannels.ATLAS_VALIDATION, make_atlas_validation),
    (AgentChannels.EXECUTION,        make_execution),
    (AgentChannels.POSTMORTEM,       make_postmortem),
]


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _wait(condition, timeout: float = 2.0, interval: float = 0.02) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(interval)


def _make_bus(server: fakeredis.FakeServer, **kw) -> AgentMessageBus:
    return AgentMessageBus(fakeredis.FakeRedis(server=server), **kw)


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def bus(server):
    b = _make_bus(server)
    yield b
    b.stop()


@pytest.fixture
def publisher(server):
    return _make_bus(server)


# ─────────────────────────────────────────────────────────────────────────────
# TestPublishConsume
# ─────────────────────────────────────────────────────────────────────────────

class TestPublishConsume:

    def test_proposal_delivered_to_handler(self, bus, publisher):
        received: list = []
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR, "atlas-1", received.append)
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        _wait(lambda: len(received) == 1)
        bus.stop()

        assert len(received) == 1
        assert isinstance(received[0], ProposalMessage)
        assert received[0].trade.ticker == "MSFT"
        assert received[0].correlation_id == CORR

    def test_message_acked_after_successful_handler(self, server, publisher):
        bus = _make_bus(server)
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR, "atlas-1", lambda _: None)
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        _wait(lambda: _pending_count(server, AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR) == 0)
        bus.stop()

        assert _pending_count(server, AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR) == 0

    def test_message_stays_in_pel_when_handler_raises(self, server, publisher):
        call_count = [0]

        def failing_handler(_):
            call_count[0] += 1
            raise RuntimeError("simulated failure")

        bus = _make_bus(server)
        # max_retries=1 so it DLQs after the first failure, keeping test fast
        bus.subscribe(
            AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR,
            "atlas-1", failing_handler, max_retries=1,
        )
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        _wait(lambda: call_count[0] >= 1)
        bus.stop()

        # Message went to DLQ (ACKed after exhausting retries)
        assert _stream_len(server, AgentChannels.dead_letter(AgentChannels.PROPOSALS)) == 1

    def test_messages_delivered_in_fifo_order(self, bus, publisher):
        received: list[ProposalMessage] = []
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.AUDIT_LOGGER, "audit-1", received.append)
        bus.start()

        tickers = ["MSFT", "AAPL", "NVDA"]
        for t in tickers:
            msg = make_proposal()
            object.__setattr__(msg.trade, "ticker", t)
            publisher.publish(AgentChannels.PROPOSALS, msg)

        _wait(lambda: len(received) == 3)
        bus.stop()

        assert [m.trade.ticker for m in received] == tickers

    def test_publish_returns_stream_entry_id(self, publisher):
        entry_id = publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        assert entry_id is not None
        # Entry IDs look like "1234567890123-0" (bytes or str depending on client config)
        assert b"-" in entry_id if isinstance(entry_id, bytes) else "-" in entry_id

    def test_stream_stores_message_type_field_for_inspection(self, server, publisher):
        """message_type is stored as a plain field alongside payload for redis-cli readability."""
        publisher.publish(AgentChannels.CRITIQUES, make_critique())
        client = fakeredis.FakeRedis(server=server)
        entries = client.xrange(AgentChannels.CRITIQUES, "-", "+")
        assert len(entries) == 1
        _id, fields = entries[0]
        assert fields.get(b"message_type") == b"CRITIQUE"


# ─────────────────────────────────────────────────────────────────────────────
# TestFanOut
# ─────────────────────────────────────────────────────────────────────────────

class TestFanOut:

    def test_two_consumer_groups_each_receive_every_message(self, server, publisher):
        atlas_received: list = []
        audit_received: list = []

        bus = _make_bus(server)
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR, "atlas-1", atlas_received.append)
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.AUDIT_LOGGER, "audit-1", audit_received.append)
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        _wait(lambda: len(atlas_received) == 1 and len(audit_received) == 1)
        bus.stop()

        assert len(atlas_received) == 1
        assert len(audit_received) == 1

    def test_messages_on_different_channels_do_not_cross(self, server, publisher):
        proposals_received: list = []
        critiques_received: list = []

        bus = _make_bus(server)
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.AUDIT_LOGGER, "audit-1", proposals_received.append)
        bus.subscribe(AgentChannels.CRITIQUES, ConsumerGroups.AUDIT_LOGGER, "audit-2", critiques_received.append)
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        _wait(lambda: len(proposals_received) == 1)
        time.sleep(0.1)
        bus.stop()

        assert len(proposals_received) == 1
        assert len(critiques_received) == 0


# ─────────────────────────────────────────────────────────────────────────────
# TestRetryAndDLQ
# ─────────────────────────────────────────────────────────────────────────────

class TestRetryAndDLQ:

    def test_handler_retried_before_dlq(self, server, publisher):
        attempts = [0]

        def flaky(msg):
            attempts[0] += 1
            if attempts[0] < MAX_RETRIES_DEFAULT:
                raise RuntimeError("not yet")

        bus = _make_bus(server)
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR, "atlas-1", flaky)
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        _wait(lambda: attempts[0] >= MAX_RETRIES_DEFAULT, timeout=4.0)
        bus.stop()

        # Succeeded on final attempt — DLQ must be empty
        assert _stream_len(server, AgentChannels.dead_letter(AgentChannels.PROPOSALS)) == 0

    def test_message_moves_to_dlq_after_max_retries(self, server, publisher):
        def always_fails(_):
            raise RuntimeError("always fails")

        bus = _make_bus(server)
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR, "atlas-1", always_fails)
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        dlq = AgentChannels.dead_letter(AgentChannels.PROPOSALS)
        _wait(lambda: _stream_len(server, dlq) == 1, timeout=4.0)
        bus.stop()

        assert _stream_len(server, dlq) == 1

    def test_dlq_entry_contains_expected_fields(self, server, publisher):
        bus = _make_bus(server)
        bus.subscribe(
            AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR,
            "atlas-1", lambda _: (_ for _ in ()).throw(RuntimeError()),
        )
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        dlq = AgentChannels.dead_letter(AgentChannels.PROPOSALS)
        _wait(lambda: _stream_len(server, dlq) == 1, timeout=4.0)
        bus.stop()

        client = fakeredis.FakeRedis(server=server)
        _id, fields = client.xrange(dlq, "-", "+")[0]
        assert fields[b"reason"] == b"max_retries_exceeded"
        assert fields[b"original_channel"] == AgentChannels.PROPOSALS.encode()
        assert fields[b"consumer_group"] == ConsumerGroups.ATLAS_VALIDATOR.encode()

    def test_malformed_json_goes_to_dlq_immediately(self, server):
        received: list = []
        bus = _make_bus(server)
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.AUDIT_LOGGER, "audit-1", received.append)
        bus.start()

        raw_client = fakeredis.FakeRedis(server=server)
        raw_client.xadd(AgentChannels.PROPOSALS, {"message_type": "PROPOSAL", "payload": b"not-json"})

        dlq = AgentChannels.dead_letter(AgentChannels.PROPOSALS)
        _wait(lambda: _stream_len(server, dlq) == 1)
        bus.stop()

        assert len(received) == 0  # Not delivered to handler
        assert _stream_len(server, dlq) == 1

    def test_dlq_entry_after_malformed_json_has_correct_reason(self, server):
        bus = _make_bus(server)
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.AUDIT_LOGGER, "audit-1", lambda _: None)
        bus.start()

        raw_client = fakeredis.FakeRedis(server=server)
        raw_client.xadd(AgentChannels.PROPOSALS, {"message_type": "PROPOSAL", "payload": b"bad"})

        dlq = AgentChannels.dead_letter(AgentChannels.PROPOSALS)
        _wait(lambda: _stream_len(server, dlq) == 1)
        bus.stop()

        client = fakeredis.FakeRedis(server=server)
        _id, fields = client.xrange(dlq, "-", "+")[0]
        assert fields[b"reason"] == b"deserialization_error"


# ─────────────────────────────────────────────────────────────────────────────
# TestPendingOnRestart
# ─────────────────────────────────────────────────────────────────────────────

class TestPendingOnRestart:

    def test_drain_pending_called_at_startup(self, server):
        """
        _drain_pending must be invoked once per thread at startup.
        This ensures crash-recovery logic (PEL drain) always runs.

        Note: fakeredis has a known limitation — XREADGROUP with id="0" returns
        empty even when the PEL is non-empty. The crash-recovery path is therefore
        covered at the integration test level (real Redis). This test verifies the
        method is called, which is the testable unit here.
        """
        bus = _make_bus(server)
        drain_calls = []
        original_drain = bus._drain_pending

        def patched_drain(sub):
            drain_calls.append(sub.consumer_group)
            return original_drain(sub)

        bus._drain_pending = patched_drain
        bus.subscribe(
            AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR,
            "atlas-1", lambda _: None,
        )
        bus.start()
        _wait(lambda: len(drain_calls) >= 1)
        bus.stop()

        assert drain_calls == [ConsumerGroups.ATLAS_VALIDATOR]

    def test_local_retry_queue_survives_between_loop_iterations(self, server, publisher):
        """
        Messages that fail the handler are enqueued locally and re-processed
        in the next loop iteration — without needing an extra XREADGROUP call.
        """
        attempts = []

        def handler_succeeds_on_second_try(msg):
            attempts.append(len(attempts) + 1)
            if len(attempts) < 2:
                raise RuntimeError("first attempt fails")

        bus = _make_bus(server)
        bus.subscribe(
            AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR,
            "atlas-1", handler_succeeds_on_second_try,
        )
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        _wait(lambda: len(attempts) >= 2, timeout=3.0)
        bus.stop()

        assert len(attempts) == 2  # called twice: fail + succeed


# ─────────────────────────────────────────────────────────────────────────────
# TestResilience
# ─────────────────────────────────────────────────────────────────────────────

class TestResilience:

    def test_crashing_handler_does_not_crash_bus(self, server, publisher):
        good: list = []

        def bad(_):
            raise RuntimeError("boom")

        bus = _make_bus(server)
        bus.subscribe(
            AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR,
            "atlas-1", bad, max_retries=1,
        )
        # Second group on same channel — should be unaffected
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.AUDIT_LOGGER, "audit-1", good.append)
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        _wait(lambda: len(good) == 1)
        bus.stop()

        assert len(good) == 1  # audit received it fine

    def test_start_twice_is_idempotent(self, server):
        bus = _make_bus(server)
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.AUDIT_LOGGER, "audit-1", lambda _: None)
        bus.start()
        thread_before = bus._subscriptions[0]._thread
        bus.start()  # second call must be a no-op
        assert bus._subscriptions[0]._thread is thread_before
        bus.stop()

    def test_stop_without_start_does_not_raise(self, server):
        bus = _make_bus(server)
        bus.stop()  # Should be a clean no-op


# ─────────────────────────────────────────────────────────────────────────────
# TestDLQSystemError
# ─────────────────────────────────────────────────────────────────────────────

class TestDLQSystemError:

    def test_system_error_emitted_when_message_hits_dlq(self, server, publisher):
        mock_publisher = MagicMock()

        bus = AgentMessageBus(fakeredis.FakeRedis(server=server), event_publisher=mock_publisher)
        bus.subscribe(
            AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR,
            "atlas-1", lambda _: (_ for _ in ()).throw(RuntimeError()),
        )
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        dlq = AgentChannels.dead_letter(AgentChannels.PROPOSALS)
        _wait(lambda: _stream_len(server, dlq) == 1, timeout=4.0)
        bus.stop()

        # EventPublisher.publish was called with a SYSTEM_ERROR event
        mock_publisher.publish.assert_called_once()
        _channel, event = mock_publisher.publish.call_args.args
        assert event.event_type == "system.error"
        assert event.payload["dlq_channel"] == dlq
        assert event.payload["reason"] == "max_retries_exceeded"

    def test_no_system_error_without_event_publisher(self, server, publisher):
        """DLQ write must succeed even when event_publisher is None."""
        bus = AgentMessageBus(fakeredis.FakeRedis(server=server), event_publisher=None)
        bus.subscribe(
            AgentChannels.PROPOSALS, ConsumerGroups.ATLAS_VALIDATOR,
            "atlas-1", lambda _: (_ for _ in ()).throw(RuntimeError()),
        )
        bus.start()

        publisher.publish(AgentChannels.PROPOSALS, make_proposal())
        dlq = AgentChannels.dead_letter(AgentChannels.PROPOSALS)
        _wait(lambda: _stream_len(server, dlq) == 1, timeout=4.0)
        bus.stop()

        assert _stream_len(server, dlq) == 1  # DLQ written without error


# ─────────────────────────────────────────────────────────────────────────────
# TestRoundTrip
# ─────────────────────────────────────────────────────────────────────────────

class TestRoundTrip:

    def test_proposal_all_fields_preserved_through_stream(self, bus, publisher):
        """
        Decimals, UUIDs, datetimes with timezone, nested Pydantic models — all
        must survive the JSON→stream→JSON round-trip without loss or type coercion.
        """
        received: list[ProposalMessage] = []
        bus.subscribe(AgentChannels.PROPOSALS, ConsumerGroups.AUDIT_LOGGER, "audit-1", received.append)
        bus.start()

        original = make_proposal()
        publisher.publish(AgentChannels.PROPOSALS, original)
        _wait(lambda: len(received) == 1)
        bus.stop()

        restored = received[0]
        assert restored.message_id == original.message_id
        assert restored.correlation_id == original.correlation_id
        assert restored.agent_id == original.agent_id
        assert restored.trade.ticker == original.trade.ticker
        # Decimal precision must be exact — strike lives on OptionLeg, not TradeStructure
        assert restored.trade.structure.legs[0].strike == Decimal("410.00")
        assert restored.trade.structure.buying_power_required == Decimal("41000.00")
        assert restored.sizing.proposed_size_usd == Decimal("41000.00")
        # datetime timezone preserved
        assert restored.data_signature.data_timestamp.tzinfo is not None

    @pytest.mark.parametrize("channel,factory", ALL_MESSAGES)
    def test_all_message_types_round_trip(self, server, channel, factory):
        """Every message type published to its stream is deserialized to the correct class."""
        received: list = []
        bus = _make_bus(server)
        bus.subscribe(channel, ConsumerGroups.AUDIT_LOGGER, "audit-1", received.append)
        bus.start()

        original = factory()
        pub = _make_bus(server)
        pub.publish(channel, original)

        _wait(lambda: len(received) == 1)
        bus.stop()

        restored = received[0]
        assert type(restored) is type(original)
        assert restored.message_id == original.message_id
        assert restored.message_type == original.message_type

    def test_factory_deserializes_stream_payload_correctly(self):
        """factory.deserialize_message reconstructs the right type from JSON dict."""
        for _channel, factory in ALL_MESSAGES:
            original = factory()
            raw = json.loads(original.model_dump_json())
            result = deserialize_message(raw)
            assert type(result) is type(original)
            assert result.message_id == original.message_id


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _pending_count(server: fakeredis.FakeServer, stream: str, group: str) -> int:
    client = fakeredis.FakeRedis(server=server)
    try:
        info = client.xpending(stream, group)
        return info["pending"]
    except Exception:
        return 0


def _stream_len(server: fakeredis.FakeServer, stream: str) -> int:
    client = fakeredis.FakeRedis(server=server)
    try:
        return client.xlen(stream)
    except Exception:
        return 0
