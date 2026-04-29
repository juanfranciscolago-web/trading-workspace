"""
TelegramSink — sends formatted alerts via python-telegram-bot.

Retry policy (exponential backoff with jitter):
- On 429 (rate limited): respect retry_after from Telegram response if present,
  else use 2^attempt + random(0, 1) seconds. Max 3 attempts.
- On NetworkError / TimedOut: exponential backoff, max 3 attempts.
- On BadRequest (Markdown parse failure): one plain-text fallback attempt,
  then raise TelegramSinkError if that also fails.
- On any other error: raise TelegramSinkError immediately (no retry).

Raises TelegramSinkError on all delivery failures so the router records
the actual Telegram API error rather than the opaque "sink returned None".
"""
from __future__ import annotations

import asyncio
import logging
import os
import random

from ..events import AlertEvent
from .base import BaseSink

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


class TelegramSinkError(Exception):
    """Raised when TelegramSink fails to deliver after all retries."""


def _chat_ids() -> list[str]:
    """Return the list of allowed (and target) chat IDs from env."""
    raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def _primary_chat_id() -> str | None:
    """First ID in the whitelist = primary alert destination."""
    ids = _chat_ids()
    return ids[0] if ids else None


class TelegramSink(BaseSink):

    def __init__(self, bot=None, chat_id: str | None = None) -> None:
        self._bot = bot
        self._chat_id = chat_id or _primary_chat_id()

    def _get_bot(self):
        if self._bot is not None:
            return self._bot
        from telegram import Bot
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        return Bot(token=token)

    async def send(self, event: AlertEvent, text: str) -> str | None:
        if not self._chat_id:
            raise RuntimeError(
                "TelegramSink: TELEGRAM_ALLOWED_CHAT_IDS not set — cannot determine alert destination"
            )

        bot = self._get_bot()
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                msg = await bot.send_message(
                    chat_id=self._chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
                logger.info(
                    "TelegramSink sent event=%s message_id=%s attempt=%d",
                    event.event_type, msg.message_id, attempt,
                )
                return str(msg.message_id)

            except Exception as exc:
                last_exc = exc

                # BadRequest = Markdown parse failure — skip retries, go to plain-text fallback.
                # Must be checked before _is_retryable: in PTB v22+ BadRequest ⊂ NetworkError.
                if _is_bad_request(exc):
                    break

                retry_after = _extract_retry_after(exc)
                if retry_after is not None and attempt < _MAX_RETRIES - 1:
                    logger.warning(
                        "TelegramSink 429 — retry_after=%ss attempt=%d", retry_after, attempt
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if attempt < _MAX_RETRIES - 1 and _is_retryable(exc):
                    wait = (2 ** attempt) + random.random()
                    logger.warning(
                        "TelegramSink error — backoff %.2fs attempt=%d exc=%r",
                        wait, attempt, exc,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Non-retryable or exhausted retries — exit loop
                break

        # BadRequest usually means Markdown parse failure. One plain-text retry.
        if last_exc is not None and _is_bad_request(last_exc):
            plain = _strip_markdown(text)
            logger.warning(
                "TelegramSink: Markdown rejected (%r) — retrying as plain text for event=%s",
                last_exc, event.event_type,
            )
            try:
                msg = await bot.send_message(chat_id=self._chat_id, text=plain)
                logger.info(
                    "TelegramSink plain-text fallback succeeded message_id=%s event=%s",
                    msg.message_id, event.event_type,
                )
                return str(msg.message_id)
            except Exception as exc2:
                last_exc = exc2
                logger.error(
                    "TelegramSink plain-text fallback also failed event=%s: %r",
                    event.event_type, exc2,
                )

        logger.error(
            "TelegramSink failed event=%s after %d attempt(s): %r",
            event.event_type, _MAX_RETRIES, last_exc,
        )
        raise TelegramSinkError(
            f"Telegram delivery failed for {event.event_type.value!r}: {last_exc}"
        ) from last_exc


def _strip_markdown(text: str) -> str:
    """Remove MarkdownV1 control characters for plain-text fallback."""
    return (
        text
        .replace(r"\_", "_")   # unescape escaped underscores first
        .replace(r"\*", "*")   # unescape escaped asterisks
        .replace(r"\`", "`")   # unescape escaped backticks
        .replace("*", "")      # remove bold/italic markers
        .replace("_", " ")     # replace italic markers with space
        .replace("`", "")      # remove code markers
    )


def _extract_retry_after(exc: Exception) -> float | None:
    """Extract retry_after seconds from a Telegram 429 response if available."""
    try:
        from telegram.error import RetryAfter
        if isinstance(exc, RetryAfter):
            return float(exc.retry_after)
    except ImportError:
        pass
    ra = getattr(exc, "retry_after", None)
    if ra is not None:
        return float(ra)
    return None


def _is_retryable(exc: Exception) -> bool:
    """Only network/timeout errors are retried; API errors are not."""
    try:
        from telegram.error import NetworkError, TimedOut
        return isinstance(exc, (NetworkError, TimedOut))
    except ImportError:
        return False


def _is_bad_request(exc: Exception) -> bool:
    """True for Telegram 400 Bad Request (typically malformed Markdown)."""
    try:
        from telegram.error import BadRequest
        return isinstance(exc, BadRequest)
    except ImportError:
        return False
