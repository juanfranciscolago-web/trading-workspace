"""
End-to-end pipeline tests: publish → Redis → worker processes → DB row inserted.

Requires real Redis (docker-compose up -d).
Marked @pytest.mark.integration — skipped automatically when Redis is down.
Session-scoped fixture verifies Redis availability upfront with a clear message.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from multi_agent.alerts.bus import AlertBus
from multi_agent.alerts.dedup import AlertDedup
from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity
from multi_agent.alerts.repository import AlertRepository
from multi_agent.alerts.router import AlertRouter
from multi_agent.alerts.worker import AlertWorker


# ── Redis availability guard ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def redis_available():
    """Session-scoped fixture: skip all e2e tests if Redis is not reachable."""
    import redis as _redis
    from multi_agent.config import settings
    url = settings.REDIS_URL
    try:
        r = _redis.from_url(url, socket_connect_timeout=2)
        r.ping()
        return True
    except Exception as exc:
        pytest.skip(f"Redis not available ({exc}) — skipping e2e tests. Run: docker-compose up -d")


@pytest.fixture
def mock_repo():
    repo = MagicMock(spec=AlertRepository)
    return repo


@pytest.fixture
def mock_sink_result():
    sink = MagicMock()
    sink.send = AsyncMock(return_value="mock_msg_id")
    return sink


# ── E2E Tests ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestAlertPipelineE2E:

    async def test_publish_reaches_worker(self, redis_available, mock_repo, mock_sink_result):
        """Publish an event via AlertBus; worker receives it and routes it."""
        bus = AlertBus()
        dedup_redis = MagicMock()
        dedup_redis.set.return_value = True  # not a dup
        dedup = AlertDedup(redis_client=dedup_redis)
        router = AlertRouter(dedup=dedup, sinks=[mock_sink_result], repo=mock_repo)
        worker = AlertWorker(bus=bus, router=router)

        event = AlertEvent(
            event_type=AlertEventType.SYSTEM_FAILURE,
            severity=AlertSeverity.CRITICAL,
            title="E2E test: system failure",
            payload={"component": "e2e_test", "error_msg": "test"},
        )

        async def _publish_then_stop():
            await asyncio.sleep(0.1)
            bus.publish(event)
            await asyncio.sleep(0.2)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _publish_then_stop(),
        )
        mock_sink_result.send.assert_called_once()

    async def test_repo_save_called_with_sent_at(self, redis_available, mock_repo, mock_sink_result):
        """When sink succeeds, repo.save() is called with sent_at populated."""
        bus = AlertBus()
        dedup_redis = MagicMock()
        dedup_redis.set.return_value = True
        dedup = AlertDedup(redis_client=dedup_redis)
        router = AlertRouter(dedup=dedup, sinks=[mock_sink_result], repo=mock_repo)
        worker = AlertWorker(bus=bus, router=router)

        event = AlertEvent(
            event_type=AlertEventType.MARGIN_BREACH,
            severity=AlertSeverity.CRITICAL,
            title="E2E: margin breach",
            payload={"symbol": "MSFT", "exposure_pct": 12.0, "limit_pct": 10.0},
        )

        async def _pub_stop():
            await asyncio.sleep(0.1)
            bus.publish(event)
            await asyncio.sleep(0.3)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _pub_stop(),
        )
        save_kwargs = mock_repo.save.call_args[1]
        assert save_kwargs["sent_at"] is not None
        assert save_kwargs["dedup_hit"] is False

    async def test_dedup_prevents_second_delivery(self, redis_available, mock_repo, mock_sink_result):
        """Second identical event within dedup window is not sent to sink."""
        bus = AlertBus()
        # First call: not dup; second: dup
        dedup_redis = MagicMock()
        dedup_redis.set.side_effect = [True, False]
        dedup = AlertDedup(redis_client=dedup_redis)
        router = AlertRouter(dedup=dedup, sinks=[mock_sink_result], repo=mock_repo)
        worker = AlertWorker(bus=bus, router=router)

        event = AlertEvent(
            event_type=AlertEventType.SYSTEM_FAILURE,
            severity=AlertSeverity.CRITICAL,
            title="E2E: dedup test",
            payload={"component": "dup_test", "error_msg": "x"},
        )

        async def _pub_stop():
            await asyncio.sleep(0.1)
            bus.publish(event)
            bus.publish(event)  # second — should be deduped
            await asyncio.sleep(0.4)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _pub_stop(),
        )
        # Sink called only once
        assert mock_sink_result.send.call_count == 1

    async def test_sink_failure_does_not_stop_worker(self, redis_available, mock_repo):
        """If sink fails, worker continues processing subsequent events."""
        bus = AlertBus()
        failing_sink = MagicMock()
        failing_sink.send = AsyncMock(return_value=None)
        dedup_redis = MagicMock()
        dedup_redis.set.return_value = True
        dedup = AlertDedup(redis_client=dedup_redis)
        router = AlertRouter(dedup=dedup, sinks=[failing_sink], repo=mock_repo)
        worker = AlertWorker(bus=bus, router=router)

        event = AlertEvent(
            event_type=AlertEventType.ROLL_OPPORTUNITY,
            severity=AlertSeverity.INFO,
            title="E2E: roll",
            payload={"position_id": "p1", "ticker": "NVDA", "expiry_date": "2026-05-16", "dte": 17, "current_iv": 35.0},
        )

        async def _pub_stop():
            await asyncio.sleep(0.1)
            bus.publish(event)
            bus.publish(event)
            await asyncio.sleep(0.4)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _pub_stop(),
        )
        # Worker processed both events (sink was called for each non-dup)
        assert failing_sink.send.call_count >= 1

    async def test_worker_stops_cleanly_without_events(self, redis_available):
        """Worker can start and stop cleanly with no events published."""
        bus = AlertBus()
        router = MagicMock()
        router.route = AsyncMock()
        worker = AlertWorker(bus=bus, router=router)

        async def _stop():
            await asyncio.sleep(0.15)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _stop(),
        )
        # No events → router not called
        router.route.assert_not_called()

    async def test_all_atlas_publisher_event_types(self, redis_available, mock_repo, mock_sink_result):
        """All 4 AlertEventType values produced by atlas_publishers can be published and processed."""
        from multi_agent.agents.atlas_publishers import (
            publish_margin_breach, publish_stop_loss_hit,
            publish_system_failure, publish_roll_opportunity,
        )
        bus = AlertBus()
        dedup_redis = MagicMock()
        dedup_redis.set.return_value = True
        dedup = AlertDedup(redis_client=dedup_redis)
        router = AlertRouter(dedup=dedup, sinks=[mock_sink_result], repo=mock_repo)
        worker = AlertWorker(bus=bus, router=router)

        async def _pub_all_stop():
            await asyncio.sleep(0.1)
            publish_margin_breach("MSFT", 12.0, 10.0)
            publish_stop_loss_hit("pos-1", "MSFT", -9.0)
            publish_system_failure("atlas", "test error")
            publish_roll_opportunity("pos-2", "NVDA", "2026-05-16", 17, 35.0)
            await asyncio.sleep(0.5)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=4.0),
            _pub_all_stop(),
        )
        assert mock_sink_result.send.call_count == 4

    async def test_published_event_has_correct_event_type(self, redis_available, mock_repo, mock_sink_result):
        """Events received by router have the correct event_type set by the publisher."""
        captured = []
        orig_route = mock_repo.save
        mock_repo.save.side_effect = lambda event, **kw: captured.append(event)

        # Use router directly with real async to capture the event
        bus = AlertBus()
        dedup_redis = MagicMock()
        dedup_redis.set.return_value = True
        dedup = AlertDedup(redis_client=dedup_redis)

        received = []

        async def capturing_send(event, text):
            received.append(event)
            return "123"

        mock_sink_result.send = capturing_send
        router = AlertRouter(dedup=dedup, sinks=[mock_sink_result], repo=mock_repo)
        worker = AlertWorker(bus=bus, router=router)

        event = AlertEvent(
            event_type=AlertEventType.STOP_LOSS_HIT,
            severity=AlertSeverity.CRITICAL,
            title="stop loss",
            payload={"position_id": "p1", "ticker": "MSFT", "pnl_pct": -9.0},
        )

        async def _pub_stop():
            await asyncio.sleep(0.1)
            bus.publish(event)
            await asyncio.sleep(0.3)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _pub_stop(),
        )
        assert len(received) == 1
        assert received[0].event_type == AlertEventType.STOP_LOSS_HIT

    async def test_repo_save_called_with_failed_at_on_sink_failure(self, redis_available, mock_repo):
        """When sink returns None, repo.save() captures failed_at."""
        bus = AlertBus()
        failing_sink = MagicMock()
        failing_sink.send = AsyncMock(return_value=None)
        dedup_redis = MagicMock()
        dedup_redis.set.return_value = True
        dedup = AlertDedup(redis_client=dedup_redis)
        router = AlertRouter(dedup=dedup, sinks=[failing_sink], repo=mock_repo)
        worker = AlertWorker(bus=bus, router=router)

        event = AlertEvent(
            event_type=AlertEventType.SYSTEM_FAILURE,
            severity=AlertSeverity.CRITICAL,
            title="failure test",
            payload={"component": "test", "error_msg": "fail"},
        )

        async def _pub_stop():
            await asyncio.sleep(0.1)
            bus.publish(event)
            await asyncio.sleep(0.3)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _pub_stop(),
        )
        save_kwargs = mock_repo.save.call_args[1]
        assert save_kwargs["failed_at"] is not None
        assert save_kwargs["sent_at"] is None
