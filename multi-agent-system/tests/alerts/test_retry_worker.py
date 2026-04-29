"""
Unit tests for RetryWorker.
All DB and Telegram calls are mocked — no real services required.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity
from multi_agent.alerts.retry_worker import RetryWorker, _row_to_event
from multi_agent.alerts.sinks.telegram import TelegramSinkError


# ── Helpers ───────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 4, 29, 15, 0, 0, tzinfo=timezone.utc)
_ORIGINAL_AT = datetime(2026, 4, 29, 14, 30, 0, tzinfo=timezone.utc)  # 30 min ago


def _row(retry_count: int = 0) -> dict:
    return {
        "id": 42,
        "event_type": "system.failure",
        "severity": "CRITICAL",
        "title": "Test failure",
        "payload": {"payload": {"component": "test", "error_msg": "boom"}},
        "retry_count": retry_count,
        "failed_at": _ORIGINAL_AT + timedelta(minutes=5),
        "last_retry_at": None if retry_count == 0 else _ORIGINAL_AT + timedelta(minutes=6),
        "error_msg": "simulated",
        "correlation_id": None,
        "created_at": _ORIGINAL_AT,
    }


def _make_worker(rows=None, sink_result="msg-99"):
    mock_repo = MagicMock()
    mock_repo.list_eligible_retries.return_value = rows if rows is not None else []
    mock_sink = MagicMock()
    if isinstance(sink_result, Exception):
        mock_sink.send = AsyncMock(side_effect=sink_result)
    else:
        mock_sink.send = AsyncMock(return_value=sink_result)
    worker = RetryWorker(sink=mock_sink, repo=mock_repo, interval=30)
    return worker, mock_repo, mock_sink


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRetryWorker:

    async def test_no_eligible_alerts_does_nothing(self):
        """When repo returns empty list, sink is never called."""
        worker, mock_repo, mock_sink = _make_worker(rows=[])

        async def _stop():
            await asyncio.sleep(0.15)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _stop(),
        )
        mock_sink.send.assert_not_called()
        mock_repo.mark_retry_claimed.assert_not_called()

    async def test_eligible_alert_retried_and_succeeds(self):
        """When repo returns a row and sink succeeds, mark_retry_success is called."""
        worker, mock_repo, mock_sink = _make_worker(rows=[_row(retry_count=0)])

        async def _stop():
            await asyncio.sleep(0.15)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _stop(),
        )
        mock_sink.send.assert_called_once()
        mock_repo.mark_retry_success.assert_called_once_with(42, "msg-99")
        mock_repo.mark_retry_failure.assert_not_called()
        mock_repo.mark_given_up.assert_not_called()

    async def test_retry_failure_below_limit_calls_mark_failure(self):
        """When sink raises and attempt < 4, mark_retry_failure is called (not mark_given_up)."""
        exc = TelegramSinkError("network gone")
        worker, mock_repo, mock_sink = _make_worker(
            rows=[_row(retry_count=1)],
            sink_result=exc,
        )

        async def _stop():
            await asyncio.sleep(0.15)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _stop(),
        )
        mock_repo.mark_retry_failure.assert_called_once()
        call_args = mock_repo.mark_retry_failure.call_args
        assert call_args[0][0] == 42  # alert_id
        assert "network gone" in call_args[0][1]
        mock_repo.mark_given_up.assert_not_called()

    async def test_retry_failure_at_limit_calls_mark_given_up(self):
        """When sink raises and attempt == 4, mark_given_up is called (not mark_retry_failure)."""
        exc = TelegramSinkError("forbidden")
        worker, mock_repo, mock_sink = _make_worker(
            rows=[_row(retry_count=3)],  # attempt = 4
            sink_result=exc,
        )

        async def _stop():
            await asyncio.sleep(0.15)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _stop(),
        )
        mock_repo.mark_given_up.assert_called_once()
        call_args = mock_repo.mark_given_up.call_args
        assert call_args[0][0] == 42
        assert "forbidden" in call_args[0][1]
        mock_repo.mark_retry_failure.assert_not_called()

    async def test_claim_called_before_sink(self):
        """mark_retry_claimed must be called before sink.send (claim-then-deliver order)."""
        call_order = []

        mock_repo = MagicMock()
        mock_repo.list_eligible_retries.return_value = [_row(retry_count=0)]
        mock_repo.mark_retry_claimed.side_effect = lambda _: call_order.append("claimed")

        mock_sink = MagicMock()

        async def _send(event, text):
            call_order.append("sent")
            return "msg-1"

        mock_sink.send = _send
        worker = RetryWorker(sink=mock_sink, repo=mock_repo, interval=30)

        async def _stop():
            await asyncio.sleep(0.15)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _stop(),
        )
        assert call_order == ["claimed", "sent"], f"Unexpected order: {call_order}"

    async def test_shutdown_is_faster_than_interval(self):
        """Worker stops well within 5s when interval=30s — shutdown does not wait full sleep."""
        worker, _, _ = _make_worker(rows=[])

        import time
        start = time.monotonic()

        async def _stop():
            await asyncio.sleep(0.3)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=10.0),
            _stop(),
        )
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"Shutdown took {elapsed:.1f}s — should be < 5s"

    async def test_multiple_eligible_alerts_all_retried(self):
        """All rows returned by repo are processed in a single poll cycle."""
        rows = [_row(retry_count=0), {**_row(retry_count=1), "id": 43}]
        worker, mock_repo, mock_sink = _make_worker(rows=rows)

        async def _stop():
            await asyncio.sleep(0.15)
            worker.shutdown()

        await asyncio.gather(
            asyncio.wait_for(worker.run(), timeout=3.0),
            _stop(),
        )
        assert mock_sink.send.call_count == 2
        assert mock_repo.mark_retry_success.call_count == 2

    async def test_retry_delay_min_passed_to_format_alert(self):
        """format_alert is called with retry_delay_min > 0 (event was created in the past)."""
        worker, mock_repo, mock_sink = _make_worker(rows=[_row(retry_count=0)])

        with patch("multi_agent.alerts.retry_worker.format_alert") as mock_fmt:
            mock_fmt.return_value = "formatted text"

            async def _stop():
                await asyncio.sleep(0.15)
                worker.shutdown()

            await asyncio.gather(
                asyncio.wait_for(worker.run(), timeout=3.0),
                _stop(),
            )

        mock_fmt.assert_called_once()
        kwargs = mock_fmt.call_args[1]
        assert "retry_delay_min" in kwargs
        assert kwargs["retry_delay_min"] >= 1  # at least 1 min (event was 30 min ago)


class TestRowToEvent:

    def test_preserves_original_created_at(self):
        """_row_to_event() uses created_at from the DB row, not datetime.now()."""
        original_ts = datetime(2026, 4, 29, 12, 0, 0, tzinfo=timezone.utc)
        row = {**_row(), "created_at": original_ts}
        event = _row_to_event(row)
        assert event.created_at == original_ts

    def test_extracts_nested_payload(self):
        """payload column stores full event JSON; _row_to_event extracts the nested payload."""
        row = _row()  # payload = {"payload": {"component": "test", "error_msg": "boom"}}
        event = _row_to_event(row)
        assert event.payload == {"component": "test", "error_msg": "boom"}

    def test_event_type_parsed_correctly(self):
        row = {**_row(), "event_type": "position.margin_breach"}
        event = _row_to_event(row)
        assert event.event_type == AlertEventType.MARGIN_BREACH

    def test_handles_null_payload_column(self):
        """When payload column is NULL (empty payload on original event), returns empty dict."""
        row = {**_row(), "payload": None}
        event = _row_to_event(row)
        assert event.payload == {}

    def test_handles_null_correlation_id(self):
        row = {**_row(), "correlation_id": None}
        event = _row_to_event(row)
        assert event.correlation_id is None
