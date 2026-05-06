from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class AgentsRepository:
    """Repository for agents.config and agents.state tables."""

    def __init__(self, pool) -> None:
        self._pool = pool

    def list_agents(self) -> list[dict]:
        """List all agents with config + state, ordered by agent_id."""
        sql = """
            SELECT
                c.agent_id,
                c.display_name,
                c.role,
                c.time_horizon_min_days,
                c.time_horizon_max_days,
                c.default_llm_model,
                c.max_portfolio_pct,
                c.is_active,
                s.status,
                s.current_task,
                s.last_heartbeat,
                s.last_proposal_at,
                s.last_error,
                s.error_count_24h,
                s.llm_cost_today_usd
            FROM agents.config c
            LEFT JOIN agents.state s USING (agent_id)
            ORDER BY c.agent_id ASC
        """
        with self._pool.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        return [dict(zip(cols, row)) for row in rows]

    def set_active(self, agent_id: str, is_active: bool) -> bool:
        """Toggle agent active state. Returns True if updated, False if not found."""
        sql = """
            UPDATE agents.config
            SET is_active = %s, updated_at = NOW()
            WHERE agent_id = %s
        """
        with self._pool.cursor() as cur:
            cur.execute(sql, (is_active, agent_id))
            return cur.rowcount > 0
