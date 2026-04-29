"""
Telegram command auth — chat_id whitelist.

TELEGRAM_ALLOWED_CHAT_IDS: comma-separated integer chat IDs in .env.
First ID = primary alert destination (TelegramSink target).

Fail-closed: if TELEGRAM_ALLOWED_CHAT_IDS is empty or unset, ALL requests
are denied. This prevents accidental data leakage from an unconfigured bot.
"""
from __future__ import annotations

import functools
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


def _load_allowed_ids() -> frozenset[int]:
    raw = os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS", "")
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                logger.warning("TELEGRAM_ALLOWED_CHAT_IDS: invalid entry %r — skipped", part)
    if not ids:
        logger.warning(
            "TELEGRAM_ALLOWED_CHAT_IDS is empty — all Telegram commands will be denied (fail-closed)"
        )
    return frozenset(ids)


def require_auth(handler):
    """
    Decorator for PTB command handlers.
    Denies the request if the sender's chat_id is not in TELEGRAM_ALLOWED_CHAT_IDS.
    Fail-closed: empty whitelist → deny all.
    """
    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        allowed = _load_allowed_ids()
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id not in allowed:
            logger.warning(
                "Telegram auth denied chat_id=%s (not in whitelist)", chat_id
            )
            if update.message:
                await update.message.reply_text("⛔ No autorizado.")
            return
        return await handler(update, context)
    return wrapper
