"""
AlertRepository — write/read alerts.sent_alerts.

save(): called by AlertRouter after each sink dispatch (or dedup hit).
list_alerts(): called by GET /alerts for paginated history.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from .events import AlertEvent

logger = logging.getLogger(__name__)


class AlertRepository:

    def __init__(self, pool) -> None:
        self._pool = pool

    def save(
        self,
        event: AlertEvent,
        *,
        dedup_key: str | None,
        dedup_hit: bool,
        sink: str = "telegram",
        sink_message_id: str | None = None,
        sent_at: datetime | None = None,
        failed_at: datetime | None = None,
        error_msg: str | None = None,
    ) -> None:
        with self._pool.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alerts.sent_alerts
                    (event_type, severity, title, dedup_key, dedup_hit,
                     sink, sink_message_id, sent_at, failed_at, error_msg,
                     payload, source, correlation_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.event_type.value,
                    event.severity.value,
                    event.title,
                    dedup_key,
                    dedup_hit,
                    sink,
                    sink_message_id,
                    sent_at,
                    failed_at,
                    error_msg,
                    event.model_dump_json() if event.payload else None,
                    event.source,
                    str(event.correlation_id) if event.correlation_id else None,
                ),
            )
        logger.debug(
            "AlertRepository.save event=%s dedup_hit=%s sink_msg=%s",
            event.event_type, dedup_hit, sink_message_id,
        )

    # ── Retry queue methods ───────────────────────────────────────────────────

    def list_eligible_retries(self, limit: int = 50) -> list[dict]:
        """Return alerts eligible for retry, claiming them atomically.

        Backoff windows by retry_count:
          0 → >=30s  from failed_at     (last_retry_at IS NULL)
          1 → >=2min from last_retry_at
          2 → >=5min from last_retry_at
          3 → >=15min from last_retry_at
        FOR UPDATE SKIP LOCKED is safe for future multi-worker deployments.
        """
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id, event_type, severity, title, payload,
                    retry_count, failed_at, last_retry_at, error_msg,
                    correlation_id, created_at
                FROM alerts.sent_alerts
                WHERE
                    failed_at IS NOT NULL
                    AND sent_at IS NULL
                    AND given_up_at IS NULL
                    AND retry_count < 4
                    AND (
                        (retry_count = 0
                         AND last_retry_at IS NULL
                         AND failed_at <= NOW() - INTERVAL '30 seconds')
                        OR (retry_count = 1
                            AND last_retry_at <= NOW() - INTERVAL '2 minutes')
                        OR (retry_count = 2
                            AND last_retry_at <= NOW() - INTERVAL '5 minutes')
                        OR (retry_count = 3
                            AND last_retry_at <= NOW() - INTERVAL '15 minutes')
                    )
                ORDER BY failed_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                [limit],
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if rows else []
        return [dict(zip(cols, r)) for r in rows]

    def mark_retry_claimed(self, alert_id: int) -> None:
        """Set last_retry_at=NOW() so this row is excluded from the next poll cycle."""
        with self._pool.cursor() as cur:
            cur.execute(
                "UPDATE alerts.sent_alerts SET last_retry_at = NOW() WHERE id = %s",
                [alert_id],
            )

    def mark_retry_success(self, alert_id: int, sink_message_id: str) -> None:
        """Record successful retry delivery — terminal success state."""
        with self._pool.cursor() as cur:
            cur.execute(
                """
                UPDATE alerts.sent_alerts
                SET sent_at = NOW(),
                    sink_message_id = %s,
                    retry_count = retry_count + 1,
                    last_retry_at = NOW()
                WHERE id = %s
                """,
                [sink_message_id, alert_id],
            )
        logger.debug("AlertRepository.mark_retry_success id=%d msg=%s", alert_id, sink_message_id)

    def mark_retry_failure(self, alert_id: int, error_msg: str) -> None:
        """Record a failed retry attempt — alert remains eligible for next window."""
        with self._pool.cursor() as cur:
            cur.execute(
                """
                UPDATE alerts.sent_alerts
                SET retry_count = retry_count + 1,
                    last_retry_at = NOW(),
                    error_msg = %s
                WHERE id = %s
                """,
                [error_msg[:512], alert_id],
            )
        logger.debug("AlertRepository.mark_retry_failure id=%d", alert_id)

    def mark_given_up(self, alert_id: int, error_msg: str) -> None:
        """Record terminal failure after exhausting all retry attempts."""
        with self._pool.cursor() as cur:
            cur.execute(
                """
                UPDATE alerts.sent_alerts
                SET given_up_at = NOW(),
                    retry_count = retry_count + 1,
                    last_retry_at = NOW(),
                    error_msg = %s
                WHERE id = %s
                """,
                [error_msg[:512], alert_id],
            )
        logger.warning("AlertRepository.mark_given_up id=%d", alert_id)

    def list_alerts(
        self,
        limit: int = 50,
        offset: int = 0,
        severity: str | None = None,
        event_type: str | None = None,
    ) -> list[dict]:
        conditions = []
        params: list = []
        if severity:
            conditions.append("severity = %s")
            params.append(severity)
        if event_type:
            conditions.append("event_type = %s")
            params.append(event_type)
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([limit, offset])

        with self._pool.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, event_type, severity, title, dedup_key, dedup_hit,
                       sink, sink_message_id, sent_at, failed_at, error_msg,
                       source, correlation_id, created_at
                FROM alerts.sent_alerts
                {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if rows else []
        return [dict(zip(cols, r)) for r in rows]
