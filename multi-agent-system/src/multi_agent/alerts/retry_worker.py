"""
RetryWorker — re-entrega alertas fallidas con backoff exponencial.

Backoff (4 intentos total):
  Retry 1: 30s  desde failed_at     (retry_count=0)
  Retry 2: 2min desde last_retry_at (retry_count=1)
  Retry 3: 5min desde last_retry_at (retry_count=2)
  Retry 4: 15min desde last_retry_at (retry_count=3)
  Después de retry 4 fallido → given_up_at, estado terminal.

Bypass de dedup por diseño: el worker llama a TelegramSink directamente,
nunca pasa por AlertRouter ni AlertDedup. Los retries son re-entregas
intencionales de alertas ya registradas en DB.

Shutdown inmediato: usa asyncio.Event, no espera el sleep de 30s.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from .events import AlertEvent, AlertEventType, AlertSeverity
from .formatters import format_alert
from .repository import AlertRepository
from .sinks.telegram import TelegramSink, TelegramSinkError

logger = logging.getLogger(__name__)


class RetryWorker:

    def __init__(
        self,
        sink: TelegramSink,
        repo: AlertRepository,
        interval: int = 30,
    ) -> None:
        self._sink = sink
        self._repo = repo
        self._interval = interval
        self._stop_event = asyncio.Event()

    def shutdown(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        self._stop_event.clear()
        logger.info("RetryWorker started (poll_interval=%ds)", self._interval)
        while not self._stop_event.is_set():
            await self._poll_and_retry()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=float(self._interval),
                )
            except asyncio.TimeoutError:
                continue   # normal: interval elapsed, no shutdown signal
            else:
                break      # shutdown() was called during the sleep
        logger.info("RetryWorker stopped")

    async def _poll_and_retry(self) -> None:
        rows = self._repo.list_eligible_retries()
        if rows:
            logger.info("RetryWorker: found %d eligible alert(s)", len(rows))
        for row in rows:
            if self._stop_event.is_set():
                break
            await self._retry_one(row)

    async def _retry_one(self, row: dict[str, Any]) -> None:
        alert_id: int = row["id"]
        retry_count: int = row["retry_count"]
        attempt = retry_count + 1

        ref_ts: datetime = row["last_retry_at"] if row.get("last_retry_at") else row["failed_at"]
        elapsed = (datetime.now(tz=timezone.utc) - ref_ts).total_seconds()
        logger.info(
            "Retrying alert id=%d attempt %d/4 (%.0fs since last failure)",
            alert_id, attempt, elapsed,
        )

        # TX 1: claim — sets last_retry_at=NOW() so this row is excluded
        # from the next poll cycle (prevents double-processing on re-poll)
        self._repo.mark_retry_claimed(alert_id)

        # Reconstruct AlertEvent and format text (outside any DB transaction)
        try:
            event = _row_to_event(row)
            delay_min = max(1, round(
                (datetime.now(tz=timezone.utc) - event.created_at).total_seconds() / 60
            ))
            text = format_alert(event, retry_delay_min=delay_min)
        except Exception as exc:
            logger.error("RetryWorker: cannot reconstruct event id=%d: %s", alert_id, exc)
            self._repo.mark_retry_failure(alert_id, f"reconstruct error: {exc}")
            return

        # Network call — TelegramSink handles its own transient retries internally
        try:
            msg_id = await self._sink.send(event, text)
        except TelegramSinkError as exc:
            error_msg = str(exc)
            if attempt >= 4:
                logger.error(
                    "Giving up on alert id=%d after 4 attempts. Last error: %s",
                    alert_id, error_msg,
                )
                self._repo.mark_given_up(alert_id, error_msg)
            else:
                logger.warning(
                    "Retry %d/4 failed for alert id=%d: %s",
                    attempt, alert_id, error_msg,
                )
                self._repo.mark_retry_failure(alert_id, error_msg)
            return

        logger.info("Retry succeeded for alert id=%d on attempt %d/4", alert_id, attempt)
        self._repo.mark_retry_success(alert_id, msg_id or "")


def _row_to_event(row: dict[str, Any]) -> AlertEvent:
    """Reconstruct AlertEvent from a DB row, preserving the original created_at."""
    full_data = row.get("payload") or {}
    # payload column stores event.model_dump_json() — full event JSON.
    # Extract the nested payload dict from it.
    payload_dict = full_data.get("payload", {}) if isinstance(full_data, dict) else {}
    return AlertEvent(
        event_type=AlertEventType(row["event_type"]),
        severity=AlertSeverity(row["severity"]),
        title=row["title"],
        payload=payload_dict,
        correlation_id=row.get("correlation_id"),
        created_at=row["created_at"],  # original event time, NOT now()
    )
