"""
Cross-system trade logger.

CRITICAL: Every trade — from Eolo, multi-agent, or human — must be logged here
with the correct `source` field. This is the foundation of performance
attribution between systems.

Usage:
    from shared_core.storage import TradeLogger
    from shared_core.models import TradeSource, TradeExecution

    logger_ = TradeLogger.from_env()

    logger_.log_execution(
        execution=trade_execution,  # TradeExecution object
        source=TradeSource.EOLO_V1,
    )

    # Later, query by source:
    eolo_trades = logger_.query_trades(source=TradeSource.EOLO_V1, days=30)
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Iterator

from shared_core.models import (
    TradeExecution,
    TradeOrder,
    TradeSource,
)

logger = logging.getLogger(__name__)


# =============================================================================
# SQL schema definition
# =============================================================================

SCHEMA_SQL = """
-- Schema for trade logging shared between Eolo and multi-agent system

CREATE SCHEMA IF NOT EXISTS shared;

CREATE TABLE IF NOT EXISTS shared.trades_log (
    -- Identity
    id BIGSERIAL PRIMARY KEY,
    execution_id VARCHAR(64) UNIQUE NOT NULL,

    -- Critical: source for performance attribution
    source VARCHAR(50) NOT NULL,

    -- Instrument details
    symbol VARCHAR(32) NOT NULL,
    asset_class VARCHAR(20) NOT NULL,
    option_type VARCHAR(10),                  -- NULL for non-options
    strike NUMERIC(18, 6),                    -- NULL for non-options
    expiration DATE,                          -- NULL for non-options
    underlying VARCHAR(32),                   -- NULL for non-derivatives

    -- Order details
    direction VARCHAR(10) NOT NULL,           -- "buy" or "sell"
    quantity INTEGER NOT NULL,
    fill_price NUMERIC(18, 6),
    fill_timestamp TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL,
    venue VARCHAR(32) DEFAULT 'SCHWAB',
    commissions NUMERIC(10, 4) DEFAULT 0,
    slippage_pct NUMERIC(8, 4),

    -- Strategy tagging
    strategy VARCHAR(64),

    -- Audit
    error_message TEXT,
    metadata JSONB DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Indexes for common queries
    CONSTRAINT valid_source CHECK (source IN (
        'eolo_v1', 'eolo_v2_spx', 'eolo_crypto',
        'multi_agent_athena', 'multi_agent_apollo', 'multi_agent_hermes',
        'multi_agent_nyx', 'multi_agent_vesta',
        'human_via_eolo', 'human_direct'
    ))
);

CREATE INDEX IF NOT EXISTS idx_trades_source ON shared.trades_log(source);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON shared.trades_log(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_fill_timestamp ON shared.trades_log(fill_timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON shared.trades_log(strategy);

-- Partition by month for performance at scale
-- (apply later when volume justifies)
"""


# =============================================================================
# Trade Logger
# =============================================================================

class TradeLogger:
    """
    Persists trade executions to shared.trades_log.

    Uses psycopg2 (or psycopg3) for PostgreSQL. Connection pooling expected
    via shared_core.storage.postgres_pool.
    """

    def __init__(self, connection_factory: Callable):
        """
        Args:
            connection_factory: Zero-argument callable returning a context manager
                                that yields a psycopg2 connection (e.g. pool.connection).
        """
        self._connection_factory = connection_factory

    @classmethod
    def from_env(cls) -> "TradeLogger":
        """Initialize from environment variables."""
        try:
            from shared_core.storage.postgres_pool import get_pool
            pool = get_pool()
            return cls(connection_factory=pool.connection)
        except ImportError:
            raise RuntimeError(
                "PostgreSQL pool not configured. "
                "Set DATABASE_URL env var and ensure psycopg2 is installed."
            )

    def init_schema(self) -> None:
        """Create the trades_log table and indexes if they don't exist."""
        with self._cursor() as cur:
            cur.execute(SCHEMA_SQL)
        logger.info("Trade log schema initialized")

    def log_execution(self, execution: TradeExecution) -> int:
        """
        Persist a trade execution.

        Returns:
            The auto-generated id of the new row.
        """
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO shared.trades_log (
                    execution_id, source, symbol, asset_class,
                    option_type, strike, expiration, underlying,
                    direction, quantity, fill_price, fill_timestamp,
                    status, venue, commissions, slippage_pct,
                    strategy, error_message, metadata
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (execution_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    fill_price = COALESCE(EXCLUDED.fill_price, shared.trades_log.fill_price),
                    fill_timestamp = COALESCE(EXCLUDED.fill_timestamp, shared.trades_log.fill_timestamp),
                    error_message = EXCLUDED.error_message
                RETURNING id
                """,
                (
                    execution.execution_id,
                    execution.source.value,
                    execution.instrument.symbol,
                    execution.instrument.asset_class.value,
                    execution.instrument.option_type.value if execution.instrument.option_type else None,
                    float(execution.instrument.strike) if execution.instrument.strike else None,
                    execution.instrument.expiration,
                    execution.instrument.underlying,
                    execution.direction.value,
                    execution.quantity,
                    float(execution.fill_price) if execution.fill_price else None,
                    execution.fill_timestamp,
                    execution.status.value,
                    execution.venue,
                    float(execution.commissions),
                    execution.slippage_pct,
                    execution.strategy,
                    execution.error_message,
                    json.dumps(execution.metadata),
                ),
            )
            row_id = cur.fetchone()[0]
            logger.debug(f"Logged trade: id={row_id} source={execution.source.value} "
                        f"symbol={execution.instrument.symbol}")
            return row_id

    def query_trades(
        self,
        source: TradeSource | None = None,
        symbol: str | None = None,
        strategy: str | None = None,
        days: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Query trades with optional filters."""
        clauses = []
        params: list = []

        if source:
            clauses.append("source = %s")
            params.append(source.value)
        if symbol:
            clauses.append("symbol = %s")
            params.append(symbol)
        if strategy:
            clauses.append("strategy = %s")
            params.append(strategy)
        if days:
            clauses.append("fill_timestamp >= %s")
            params.append(datetime.now(timezone.utc) - timedelta(days=days))
        if start_date:
            clauses.append("fill_timestamp >= %s")
            params.append(start_date)
        if end_date:
            clauses.append("fill_timestamp <= %s")
            params.append(end_date)

        where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
        sql = f"""
            SELECT id, execution_id, source, symbol, asset_class,
                   option_type, strike, expiration, underlying,
                   direction, quantity, fill_price, fill_timestamp,
                   status, venue, commissions, slippage_pct,
                   strategy, metadata, created_at
            FROM shared.trades_log
            {where_sql}
            ORDER BY fill_timestamp DESC NULLS LAST
        """

        with self._cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    def get_attribution_summary(
        self,
        days: int = 30,
    ) -> dict:
        """
        Performance attribution by source.

        Returns:
            dict mapping source → {trade_count, total_pnl, win_rate, ...}
        """
        with self._cursor() as cur:
            cur.execute(
                """
                SELECT
                    source,
                    COUNT(*) as trade_count,
                    COUNT(DISTINCT symbol) as unique_symbols,
                    COUNT(DISTINCT strategy) as unique_strategies,
                    AVG(slippage_pct) as avg_slippage,
                    SUM(commissions) as total_commissions
                FROM shared.trades_log
                WHERE fill_timestamp >= %s
                  AND status = 'filled'
                GROUP BY source
                ORDER BY trade_count DESC
                """,
                (datetime.now(timezone.utc) - timedelta(days=days),),
            )

            results = {}
            for row in cur.fetchall():
                source = row[0]
                results[source] = {
                    "trade_count": row[1],
                    "unique_symbols": row[2],
                    "unique_strategies": row[3],
                    "avg_slippage_pct": float(row[4]) if row[4] else None,
                    "total_commissions": float(row[5]) if row[5] else 0,
                }

            return results

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    @contextmanager
    def _cursor(self) -> Iterator:
        """Yield a cursor; commit on success, rollback on error, return conn to pool."""
        with self._connection_factory() as conn:
            try:
                with conn.cursor() as cur:
                    yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
