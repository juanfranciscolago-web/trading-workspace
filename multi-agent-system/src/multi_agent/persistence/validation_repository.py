"""
ValidationRepository — read-only access to trades.atlas_validations.

Write path will be added in Sprint 3 when the validate route is connected
to DB persistence. Currently rows come from the executor pipeline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

logger = logging.getLogger(__name__)


def _coerce_uuid(value) -> str:
    """Accept str or UUID; return str for psycopg3."""
    if isinstance(value, UUID):
        return str(value)
    return str(value)


class ValidationRepository:

    def __init__(self, pool) -> None:
        self._pool = pool

    def list_validations(
        self,
        approved: bool | None = None,
        days: int = 7,
        limit: int = 50,
    ) -> list[dict]:
        """
        Return recent validation rows from atlas_validations.

        approved=None → all rows (including Sprint 1 rows where approved IS NULL).
        approved=True → only approved=True rows.
        approved=False → only approved=False rows.

        Two SQL branches: passing NULL to psycopg3 for a boolean column raises
        IndeterminateDatatype, so approved=None uses a separate query without
        the approved= predicate.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        with self._pool.cursor() as cur:
            if approved is None:
                cur.execute(
                    """
                    SELECT correlation_id, approved, executed_size_pct, original_size_pct,
                           reason, atlas_version, portfolio_snapshot_id, evaluation_time_ms,
                           checks_passed, checks_failed, risk_mode, created_at
                    FROM trades.atlas_validations
                    WHERE created_at >= %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (since, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT correlation_id, approved, executed_size_pct, original_size_pct,
                           reason, atlas_version, portfolio_snapshot_id, evaluation_time_ms,
                           checks_passed, checks_failed, risk_mode, created_at
                    FROM trades.atlas_validations
                    WHERE approved = %s
                      AND created_at >= %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (approved, since, limit),
                )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if rows else []
        return [dict(zip(cols, r)) for r in rows]

    def get_by_correlation_id(self, correlation_id) -> dict | None:
        """Return detail row for a single validation, or None if not found."""
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT correlation_id, approved, executed_size_pct, original_size_pct,
                       reason, atlas_version, portfolio_snapshot_id, evaluation_time_ms,
                       checks_passed, checks_failed, metrics_snapshot, risk_mode, created_at
                FROM trades.atlas_validations
                WHERE correlation_id = %s
                """,
                (_coerce_uuid(correlation_id),),
            )
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if row else []
        return dict(zip(cols, row)) if row else None
