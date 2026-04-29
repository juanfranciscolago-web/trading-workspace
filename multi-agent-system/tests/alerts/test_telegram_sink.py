"""
Unit tests for TelegramSink.
Bot is mocked — no real Telegram calls.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity
from multi_agent.alerts.sinks.telegram import (
    TelegramSink,
    TelegramSinkError,
    _extract_retry_after,
    _strip_markdown,
)


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

    async def test_no_chat_id_raises_runtime_error(self):
        """No chat_id configured raises RuntimeError with actionable message."""
        sink = TelegramSink(bot=_mock_bot(), chat_id=None)
        sink._chat_id = None  # force None — no env/settings dependency
        with pytest.raises(RuntimeError, match="TELEGRAM_ALLOWED_CHAT_IDS"):
            await sink.send(_event(), "test")

    async def test_non_retryable_error_raises_with_detail(self):
        """Non-retryable failures raise TelegramSinkError with the original error message."""
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=Exception("connection refused"))
        sink = TelegramSink(bot=bot, chat_id="123")
        with pytest.raises(TelegramSinkError, match="connection refused"):
            await sink.send(_event(), "test")

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

    async def test_max_retries_exceeded_raises_after_all_attempts(self):
        """After 3 retryable failures (NetworkError), raises TelegramSinkError."""
        from telegram.error import NetworkError
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=NetworkError("connection reset"))
        sink = TelegramSink(bot=bot, chat_id="123")
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(TelegramSinkError, match="connection reset"):
                await sink.send(_event(), "test")
        assert bot.send_message.call_count == 3

    async def test_primary_chat_id_from_settings(self):
        """First ID in settings.primary_telegram_chat_id is used as alert destination."""
        bot = _mock_bot()
        with patch("multi_agent.alerts.sinks.telegram.settings") as mock_s:
            mock_s.primary_telegram_chat_id = "111"
            sink = TelegramSink(bot=bot)
        await sink.send(_event(), "test")
        assert bot.send_message.call_args[1]["chat_id"] == "111"

    async def test_bad_request_triggers_plain_text_fallback(self):
        """BadRequest (Markdown parse failure) retries once with plain text and succeeds."""
        from telegram.error import BadRequest
        bot = MagicMock()
        plain_msg = MagicMock()
        plain_msg.message_id = 77
        bot.send_message = AsyncMock(
            side_effect=[BadRequest("Can't parse entities"), plain_msg]
        )
        sink = TelegramSink(bot=bot, chat_id="123")
        result = await sink.send(_event(), "*broken _markdown_*")
        assert result == "77"
        # Second call must omit parse_mode (plain text)
        assert bot.send_message.call_count == 2
        second_call_kwargs = bot.send_message.call_args_list[1][1]
        assert "parse_mode" not in second_call_kwargs or second_call_kwargs.get("parse_mode") is None

    async def test_bad_request_plain_text_also_fails_raises_with_detail(self):
        """If plain-text fallback also fails, TelegramSinkError contains the API error detail."""
        from telegram.error import BadRequest
        bot = MagicMock()
        bot.send_message = AsyncMock(
            side_effect=[
                BadRequest("Can't parse entities: bold"),
                Exception("network gone"),
            ]
        )
        sink = TelegramSink(bot=bot, chat_id="123")
        with pytest.raises(TelegramSinkError, match="network gone"):
            await sink.send(_event(), "*broken*")

    async def test_error_message_contains_api_detail(self):
        """TelegramSinkError message includes the original Telegram error text."""
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=Exception("Forbidden: bot was blocked by the user"))
        sink = TelegramSink(bot=bot, chat_id="123")
        with pytest.raises(TelegramSinkError) as exc_info:
            await sink.send(_event(), "test")
        assert "Forbidden: bot was blocked by the user" in str(exc_info.value)


class TestStripMarkdown:

    def test_removes_bold_markers(self):
        assert "*bold*" not in _strip_markdown("*bold text*")
        assert "bold text" in _strip_markdown("*bold text*")

    def test_unescapes_underscores(self):
        # atlas\_consumer → atlas_consumer (unescape, then italic _ removed)
        result = _strip_markdown(r"atlas\_consumer")
        assert r"\_" not in result
        assert "atlas" in result

    def test_removes_backtick_markers(self):
        assert "`" not in _strip_markdown("`code`")
        assert "code" in _strip_markdown("`code`")


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
