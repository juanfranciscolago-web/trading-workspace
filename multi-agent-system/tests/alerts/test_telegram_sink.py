"""
Unit tests for TelegramSink.
Bot is mocked — no real Telegram calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity
from multi_agent.alerts.sinks.telegram import TelegramSink, _extract_retry_after


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event() -> AlertEvent:
    return AlertEvent(
        event_type=AlertEventType.MARGIN_BREACH,
        severity=AlertSeverity.WARN,
        title="MSFT margin breach",
        payload={"symbol": "MSFT", "exposure_pct": 12.5, "limit_pct": 10.0},
    )


def _mock_bot(message_id: int = 42) -> MagicMock:
    bot = MagicMock()
    msg = MagicMock()
    msg.message_id = message_id
    bot.send_message = AsyncMock(return_value=msg)
    return bot


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestTelegramSink:

    async def test_send_returns_message_id_as_string(self):
        sink = TelegramSink(bot=_mock_bot(99), chat_id="123456")
        result = await sink.send(_event(), "test message")
        assert result == "99"

    async def test_send_calls_bot_with_correct_chat_id(self):
        bot = _mock_bot()
        sink = TelegramSink(bot=bot, chat_id="777")
        await sink.send(_event(), "hello")
        bot.send_message.assert_called_once()
        assert bot.send_message.call_args[1]["chat_id"] == "777"

    async def test_send_uses_markdown_parse_mode(self):
        bot = _mock_bot()
        sink = TelegramSink(bot=bot, chat_id="123")
        await sink.send(_event(), "*bold*")
        assert bot.send_message.call_args[1]["parse_mode"] == "Markdown"

    async def test_no_chat_id_returns_none(self):
        sink = TelegramSink(bot=_mock_bot(), chat_id=None)
        with patch.dict("os.environ", {"TELEGRAM_ALLOWED_CHAT_IDS": ""}):
            result = await sink.send(_event(), "test")
        assert result is None

    async def test_bot_error_returns_none_no_raise(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=Exception("connection refused"))
        sink = TelegramSink(bot=bot, chat_id="123")
        result = await sink.send(_event(), "test")
        assert result is None

    async def test_retry_after_429_respects_retry_after(self):
        """On RetryAfter, sink must sleep the specified duration then retry."""
        from telegram.error import RetryAfter
        bot = MagicMock()
        retry_exc = RetryAfter(retry_after=1)
        success_msg = MagicMock()
        success_msg.message_id = 5
        bot.send_message = AsyncMock(side_effect=[retry_exc, success_msg])
        sink = TelegramSink(bot=bot, chat_id="123")
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await sink.send(_event(), "test")
        mock_sleep.assert_called_once_with(1.0)
        assert result == "5"

    async def test_max_retries_exceeded_returns_none(self):
        """After 3 failed retryable attempts (NetworkError), returns None without raising."""
        from telegram.error import NetworkError
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=NetworkError("connection reset"))
        sink = TelegramSink(bot=bot, chat_id="123")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await sink.send(_event(), "test")
        assert result is None
        assert bot.send_message.call_count == 3

    async def test_primary_chat_id_from_env(self):
        """First ID in TELEGRAM_ALLOWED_CHAT_IDS is used as alert destination."""
        bot = _mock_bot()
        with patch.dict("os.environ", {"TELEGRAM_ALLOWED_CHAT_IDS": "111,222,333"}):
            sink = TelegramSink(bot=bot)
        await sink.send(_event(), "test")
        assert bot.send_message.call_args[1]["chat_id"] == "111"


class TestExtractRetryAfter:

    def test_extracts_from_retry_after_exception(self):
        from telegram.error import RetryAfter
        exc = RetryAfter(retry_after=30)
        assert _extract_retry_after(exc) == 30.0

    def test_returns_none_for_generic_exception(self):
        assert _extract_retry_after(Exception("generic")) is None

    def test_extracts_float_attribute(self):
        exc = Exception("rate limited")
        exc.retry_after = 15
        assert _extract_retry_after(exc) == 15.0
