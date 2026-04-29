"""
AlertRouter — orchestrates dedup → format → sink dispatch → persist.

Each AlertEvent goes through:
1. AlertDedup.is_duplicate() — if hit, record in DB and return early
2. format_alert() — build Markdown string
3. TelegramSink.send() — deliver; capture sink_message_id or failure
4. AlertRepository.save() — persist outcome

Structured log per event:
  event_type, dedup_hit (bool), sink_latency_ms
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .dedup import AlertDedup
from .events import AlertEvent
from .formatters import format_alert
from .repository import AlertRepository
from .sinks.base import BaseSink

logger = logging.getLogger(__name__)


class AlertRouter:

    def __init__(
        self,
        dedup: AlertDedup,
        sinks: list[BaseSink],
        repo: AlertRepository,
    ) -> None:
        self._dedup = dedup
        self._sinks = sinks
        self._repo = repo

    async def route(self, event: AlertEvent) -> None:
        is_dup, dedup_key = self._dedup.is_duplicate(event)

        if is_dup:
            logger.info(
                "alert dedup_hit event=%s key=%s", event.event_type.value, dedup_key
            )
            try:
                self._repo.save(
                    event,
                    dedup_key=dedup_key,
                    dedup_hit=True,
                )
            except Exception:
                logger.exception("AlertRouter: failed to persist dedup hit")
            return

        text = format_alert(event)
        sink_message_id: str | None = None
        error_msg: str | None = None
        t0 = time.monotonic()

        for sink in self._sinks:
            try:
                result = await sink.send(event, text)
                if result is not None:
                    sink_message_id = result
                    break
                error_msg = "sink returned None"
            except Exception as exc:
                error_msg = str(exc)[:512]
                logger.exception("AlertRouter: sink error event=%s", event.event_type)

        latency_ms = (time.monotonic() - t0) * 1000
        now = datetime.now(timezone.utc)

        logger.info(
            "alert dispatched event=%s dedup_hit=False sink_latency_ms=%.1f delivered=%s",
            event.event_type.value, latency_ms, sink_message_id is not None,
        )

        try:
            self._repo.save(
                event,
                dedup_key=dedup_key,
                dedup_hit=False,
                sink_message_id=sink_message_id,
                sent_at=now if sink_message_id else None,
                failed_at=now if sink_message_id is None else None,
                error_msg=error_msg if sink_message_id is None else None,
            )
        except Exception:
            logger.exception("AlertRouter: failed to persist alert outcome")
