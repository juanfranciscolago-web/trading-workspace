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
