"""
LLM cost repository.

Reads pricing from config/llm_pricing.yaml (resolved via ATLAS_CONFIG_DIR env var
or <project_root>/config/ as fallback, same pattern as risk/config.py).

Writes to analytics.llm_costs (hypertable, partitioned by ts).
Provides 5 aggregation read methods used by GET /costs/* endpoints.
"""
from __future__ import annotations

import logging
import uuid as _uuid_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Same config dir resolution as risk/config.py
_DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


def _resolve_config_dir() -> Path:
    import os
    env = os.environ.get("ATLAS_CONFIG_DIR")
    return Path(env) if env else _DEFAULT_CONFIG_DIR


def _load_pricing(pricing_path: Path | None = None) -> dict[str, dict]:
    path = pricing_path or (_resolve_config_dir() / "llm_pricing.yaml")
    try:
        with path.open() as f:
            raw = yaml.safe_load(f)
        return raw.get("models", {})
    except Exception:
        logger.warning("LLMCostRepository: failed to load pricing from %s — costs will be 0", path)
        return {}


def _coerce_uuid(val: Any) -> _uuid_module.UUID | None:
    """Convert str/UUID/None to UUID | None for psycopg3 UUID columns."""
    if val is None:
        return None
    if isinstance(val, _uuid_module.UUID):
        return val
    try:
        return _uuid_module.UUID(str(val))
    except (ValueError, AttributeError):
        logger.debug("LLMCostRepository: could not coerce %r to UUID", val)
        return None


class LLMCostRepository:
    """
    Persists and queries LLM cost data in analytics.llm_costs.

    Use pool.cursor() for both reads and writes:
      - writes: auto-commits the INSERT
      - reads: auto-commits an empty transaction (harmless)
    """

    def __init__(self, pool, pricing_path: Path | None = None) -> None:
        self._pool = pool
        self._pricing = _load_pricing(pricing_path)

    # -------------------------------------------------------------------------
    # Write
    # -------------------------------------------------------------------------

    def log(
        self,
        *,
        agent_id: str,
        task_type: str,
        model_used: str,
        input_tokens: int,
        cache_creation_input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int,
        criticality: str = "normal",
        is_batch_api: bool = False,
        correlation_id: Any = None,
    ) -> None:
        """Insert one row into analytics.llm_costs. cost_usd is calculated here."""
        cost_usd = self._calculate_cost(
            model_used=model_used,
            input_tokens=input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            is_batch_api=is_batch_api,
        )
        with self._pool.cursor() as cur:
            cur.execute(
                """
                INSERT INTO analytics.llm_costs (
                    agent_id, task_type, model_used,
                    input_tokens, cache_creation_input_tokens, cached_input_tokens,
                    output_tokens, cost_usd, is_batch_api, criticality, correlation_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    agent_id, task_type, model_used,
                    input_tokens, cache_creation_input_tokens, cached_input_tokens,
                    output_tokens, cost_usd, is_batch_api, criticality,
                    _coerce_uuid(correlation_id),
                ),
            )
        logger.debug(
            "LLM cost logged: agent=%s task=%s model=%s cost=$%.6f",
            agent_id, task_type, model_used, cost_usd,
        )

    # -------------------------------------------------------------------------
    # Read — aggregations for GET /costs/* endpoints
    # -------------------------------------------------------------------------

    def get_summary_by_period(self, days: int = 7) -> dict[str, Any]:
        """Total cost + by-model breakdown for the period."""
        since = _since(days)
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT
                    model_used,
                    COUNT(*)                                             AS calls,
                    SUM(cost_usd)                                        AS cost_usd,
                    SUM(input_tokens + cache_creation_input_tokens
                        + cached_input_tokens + output_tokens)           AS total_tokens
                FROM analytics.llm_costs
                WHERE ts >= %s
                GROUP BY model_used
                ORDER BY cost_usd DESC
                """,
                (since,),
            )
            rows = cur.fetchall()

        if not rows:
            return {
                "total_cost_usd": 0.0,
                "total_tokens": 0,
                "total_calls": 0,
                "by_model": [],
                "period_days": days,
            }

        by_model = [
            {
                "model_used": r[0],
                "calls": int(r[1]),
                "cost_usd": float(r[2] or 0),
                "total_tokens": int(r[3] or 0),
            }
            for r in rows
        ]
        return {
            "total_cost_usd": sum(m["cost_usd"] for m in by_model),
            "total_tokens": sum(m["total_tokens"] for m in by_model),
            "total_calls": sum(m["calls"] for m in by_model),
            "by_model": by_model,
            "period_days": days,
        }

    def get_by_agent(self, days: int = 7) -> list[dict[str, Any]]:
        """Cost breakdown grouped by agent_id."""
        since = _since(days)
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT
                    agent_id,
                    COUNT(*)                                              AS calls,
                    SUM(cost_usd)                                         AS cost_usd,
                    SUM(input_tokens + cache_creation_input_tokens
                        + cached_input_tokens + output_tokens)            AS total_tokens,
                    CASE
                        WHEN SUM(input_tokens + cache_creation_input_tokens
                                 + cached_input_tokens) > 0
                        THEN CAST(SUM(cached_input_tokens) AS FLOAT)
                             / SUM(input_tokens + cache_creation_input_tokens
                                   + cached_input_tokens)
                        ELSE 0
                    END                                                   AS cache_read_ratio
                FROM analytics.llm_costs
                WHERE ts >= %s
                GROUP BY agent_id
                ORDER BY cost_usd DESC
                """,
                (since,),
            )
            rows = cur.fetchall()

        return [
            {
                "agent_id": r[0],
                "calls": int(r[1]),
                "cost_usd": float(r[2] or 0),
                "total_tokens": int(r[3] or 0),
                "cache_read_ratio": float(r[4] or 0),
            }
            for r in rows
        ]

    def get_by_task(self, days: int = 7) -> list[dict[str, Any]]:
        """Cost breakdown grouped by task_type."""
        since = _since(days)
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT
                    task_type,
                    COUNT(*)                                              AS calls,
                    SUM(cost_usd)                                         AS cost_usd,
                    AVG(input_tokens + cache_creation_input_tokens
                        + cached_input_tokens + output_tokens)            AS avg_tokens
                FROM analytics.llm_costs
                WHERE ts >= %s
                GROUP BY task_type
                ORDER BY cost_usd DESC
                """,
                (since,),
            )
            rows = cur.fetchall()

        return [
            {
                "task_type": r[0],
                "calls": int(r[1]),
                "cost_usd": float(r[2] or 0),
                "avg_tokens": float(r[3] or 0),
            }
            for r in rows
        ]

    def get_daily_totals(self, days: int = 7) -> list[dict[str, Any]]:
        """Daily cost totals, most recent first."""
        since = _since(days)
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT
                    DATE(ts)                                              AS date,
                    COUNT(*)                                              AS calls,
                    SUM(cost_usd)                                         AS cost_usd,
                    SUM(input_tokens + cache_creation_input_tokens
                        + cached_input_tokens + output_tokens)            AS total_tokens
                FROM analytics.llm_costs
                WHERE ts >= %s
                GROUP BY DATE(ts)
                ORDER BY DATE(ts) DESC
                """,
                (since,),
            )
            rows = cur.fetchall()

        return [
            {
                "date": str(r[0]),
                "calls": int(r[1]),
                "cost_usd": float(r[2] or 0),
                "total_tokens": int(r[3] or 0),
            }
            for r in rows
        ]

    def get_by_correlation_id(self, correlation_id: Any) -> list[dict[str, Any]]:
        """All cost rows for a given correlation_id (one LLM call = one row)."""
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT agent_id, task_type, model_used,
                       input_tokens, cache_creation_input_tokens,
                       cached_input_tokens, output_tokens,
                       cost_usd, is_batch_api, criticality, ts
                FROM analytics.llm_costs
                WHERE correlation_id = %s
                ORDER BY ts DESC
                """,
                (_coerce_uuid(correlation_id),),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if rows else []

        return [dict(zip(cols, r)) for r in rows]

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _calculate_cost(
        self,
        *,
        model_used: str,
        input_tokens: int,
        cache_creation_input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        is_batch_api: bool,
    ) -> float:
        pricing = self._pricing.get(model_used)
        if pricing is None:
            logger.warning(
                "LLMCostRepository: unknown model %r — cost_usd=0.0 "
                "(add it to config/llm_pricing.yaml)",
                model_used,
            )
            return 0.0

        per_m = 1_000_000

        if is_batch_api:
            batch = pricing.get("batch", {})
            input_rate = batch.get("input_per_million", pricing["input_per_million"] * 0.5)
            output_rate = batch.get("output_per_million", pricing["output_per_million"] * 0.5)
        else:
            input_rate = pricing["input_per_million"]
            output_rate = pricing["output_per_million"]

        # Cache rates are identical for standard and batch API
        cache_creation_rate = pricing.get("cache_creation_per_million", 0.0)
        cache_read_rate = pricing.get("cached_input_per_million", 0.0)

        cost = (
            input_tokens * input_rate / per_m
            + cache_creation_input_tokens * cache_creation_rate / per_m
            + cached_input_tokens * cache_read_rate / per_m
            + output_tokens * output_rate / per_m
        )
        return round(cost, 8)


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)
