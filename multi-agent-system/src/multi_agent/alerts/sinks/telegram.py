"""
TelegramSink — sends formatted alerts via python-telegram-bot.

Retry policy (exponential backoff with jitter):
- On 429 (rate limited): respect retry_after from Telegram response if present,
  else use 2^attempt + random(0, 1) seconds. Max 3 attempts.
- On other errors: log and return None (no retry — alert is logged as failed).
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
            logger.error("TelegramSink: no chat_id configured — alert dropped")
            return None

        bot = self._get_bot()
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
                retry_after = _extract_retry_after(exc)
                if retry_after is not None and attempt < _MAX_RETRIES - 1:
                    wait = retry_after
                    logger.warning(
                        "TelegramSink 429 — retry_after=%ss attempt=%d", wait, attempt
                    )
                    await asyncio.sleep(wait)
                    continue

                if attempt < _MAX_RETRIES - 1 and _is_retryable(exc):
                    wait = (2 ** attempt) + random.random()
                    logger.warning(
                        "TelegramSink error — backoff %.2fs attempt=%d exc=%s",
                        wait, attempt, exc,
                    )
                    await asyncio.sleep(wait)
                    continue

                logger.error(
                    "TelegramSink failed event=%s after %d attempts: %s",
                    event.event_type, attempt + 1, exc,
                )
                return None

        return None


def _extract_retry_after(exc: Exception) -> float | None:
    """Extract retry_after seconds from a Telegram 429 response if available."""
    try:
        from telegram.error import RetryAfter
        if isinstance(exc, RetryAfter):
            return float(exc.retry_after)
    except ImportError:
        pass
    # Fallback: check for retry_after attribute
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
