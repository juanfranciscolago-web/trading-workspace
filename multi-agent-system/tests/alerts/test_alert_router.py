"""
Unit tests for AlertRouter.
All dependencies (dedup, sink, repo) are mocked.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity
from multi_agent.alerts.router import AlertRouter


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event() -> AlertEvent:
    return AlertEvent(
        event_type=AlertEventType.MARGIN_BREACH,
        severity=AlertSeverity.CRITICAL,
        title="MSFT breach",
        payload={"symbol": "MSFT", "exposure_pct": 12.0, "limit_pct": 10.0},
    )


def _make_router(dedup_hit=False, sink_result="42"):
    dedup = MagicMock()
    dedup.is_duplicate.return_value = (dedup_hit, "alerts:dedup:margin:MSFT")

    sink = MagicMock()
    sink.send = AsyncMock(return_value=sink_result)

    repo = MagicMock()

    router = AlertRouter(dedup=dedup, sinks=[sink], repo=repo)
    return router, dedup, sink, repo


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAlertRouter:

    async def test_dedup_hit_skips_sink(self):
        router, _, sink, _ = _make_router(dedup_hit=True)
        await router.route(_event())
        sink.send.assert_not_called()

    async def test_dedup_hit_persists_with_dedup_hit_true(self):
        router, _, _, repo = _make_router(dedup_hit=True)
        await router.route(_event())
        repo.save.assert_called_once()
        assert repo.save.call_args[1]["dedup_hit"] is True

    async def test_no_dedup_dispatches_to_sink(self):
        router, _, sink, _ = _make_router(dedup_hit=False)
        await router.route(_event())
        sink.send.assert_called_once()

    async def test_successful_send_persists_with_sent_at(self):
        router, _, _, repo = _make_router(dedup_hit=False, sink_result="99")
        await router.route(_event())
        assert repo.save.call_args[1]["sink_message_id"] == "99"
        assert repo.save.call_args[1]["sent_at"] is not None
        assert repo.save.call_args[1]["failed_at"] is None

    async def test_failed_send_persists_with_failed_at(self):
        router, _, _, repo = _make_router(dedup_hit=False, sink_result=None)
        await router.route(_event())
        assert repo.save.call_args[1]["sink_message_id"] is None
        assert repo.save.call_args[1]["failed_at"] is not None

    async def test_sink_exception_does_not_raise(self):
        dedup = MagicMock()
        dedup.is_duplicate.return_value = (False, "key")
        sink = MagicMock()
        sink.send = AsyncMock(side_effect=Exception("boom"))
        repo = MagicMock()
        router = AlertRouter(dedup=dedup, sinks=[sink], repo=repo)
        # Should not raise
        await router.route(_event())

    async def test_repo_failure_does_not_raise(self):
        """Persistence errors must not interrupt the alert pipeline."""
        router, _, _, repo = _make_router()
        repo.save.side_effect = Exception("DB down")
        await router.route(_event())  # should not raise

    async def test_dedup_check_called_with_event(self):
        router, dedup, _, _ = _make_router()
        event = _event()
        await router.route(event)
        dedup.is_duplicate.assert_called_once_with(event)

    async def test_first_successful_sink_breaks_chain(self):
        """If first sink succeeds, second sink is not called."""
        dedup = MagicMock()
        dedup.is_duplicate.return_value = (False, "key")
        sink1 = MagicMock()
        sink1.send = AsyncMock(return_value="10")
        sink2 = MagicMock()
        sink2.send = AsyncMock(return_value="20")
        repo = MagicMock()
        router = AlertRouter(dedup=dedup, sinks=[sink1, sink2], repo=repo)
        await router.route(_event())
        sink1.send.assert_called_once()
        sink2.send.assert_not_called()

    async def test_dedup_key_passed_to_repo_on_success(self):
        router, _, _, repo = _make_router(dedup_hit=False)
        await router.route(_event())
        assert repo.save.call_args[1]["dedup_key"] == "alerts:dedup:margin:MSFT"
