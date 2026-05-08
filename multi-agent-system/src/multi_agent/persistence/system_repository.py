from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SystemRepository:
    """Repository for system schema (mode_history)."""

    def __init__(self, pool) -> None:
        self._pool = pool

    def get_current_mode(self) -> dict | None:
        """Latest mode change row, or None if the table is empty."""
        sql = """
            SELECT mode, changed_at, source, actor
            FROM system.mode_history
            ORDER BY changed_at DESC
            LIMIT 1
        """
        with self._pool.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))

    def insert_mode_change(
        self,
        mode: str,
        source: str,
        confirmation_token: str | None = None,
        actor: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Insert a mode change row. Returns RETURNING (mode, changed_at, source)."""
        sql = """
            INSERT INTO system.mode_history (mode, source, confirmation_token, actor, notes)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING mode, changed_at, source
        """
        with self._pool.cursor() as cur:
            cur.execute(sql, (mode, source, confirmation_token, actor, notes))
            row = cur.fetchone()
            cols = [d[0] for d in cur.description]
            result = dict(zip(cols, row))
        logger.info(
            "mode_change_recorded mode=%s source=%s actor=%s",
            mode, source, actor,
        )
        return result
