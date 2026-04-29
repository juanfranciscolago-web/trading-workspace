"""
Unit tests for AlertWorker shutdown semantics.
Bus and router are mocked — no real Redis needed.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity
from multi_agent.alerts.worker import AlertWorker


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event() -> AlertEvent:
    return AlertEvent(
        event_type=AlertEventType.SYSTEM_FAILURE,
        severity=AlertSeverity.CRITICAL,
        title="test",
        payload={"component": "test"},
    )


async def _bus_that_yields_then_stops(events, worker: AlertWorker):
    """Async generator: yields events then sets stop flag and yields None."""
    for e in events:
        yield e
    worker.shutdown()
    yield None  # gives run() a chance to see _stop


def _make_worker(events=None):
    router = MagicMock()
    router.route = AsyncMock()

    bus = MagicMock()
    worker = AlertWorker(bus=bus, router=router)

    if events is not None:
        bus.subscribe = lambda: _bus_that_yields_then_stops(events, worker)
    else:
        async def _empty():
            worker.shutdown()
            yield None
        bus.subscribe = _empty

    return worker, router


# ── Shutdown tests ────────────────────────────────────────────────────────────

class TestAlertWorkerShutdown:

    async def test_shutdown_stops_accepting_events(self):
        """After shutdown(), run() exits cleanly without processing more events."""
        worker, router = _make_worker(events=[])
        await asyncio.wait_for(worker.run(), timeout=2.0)
        # If we get here without TimeoutError, worker stopped correctly

    async def test_in_flight_tasks_drained_on_shutdown(self):
        """Events received before shutdown() are fully routed before exit."""
        event = _event()
        worker, router = _make_worker(events=[event])
        await asyncio.wait_for(worker.run(), timeout=2.0)
        # router.route must have been called for the in-flight event
        router.route.assert_called_once_with(event)

    async def test_shutdown_idempotent(self):
        """Calling shutdown() twice must not raise."""
        worker, _ = _make_worker()
        worker.shutdown()
        worker.shutdown()  # second call should be safe
        await asyncio.wait_for(worker.run(), timeout=2.0)
