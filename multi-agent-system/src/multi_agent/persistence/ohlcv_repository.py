"""OhlcvRepository — intraday + daily OHLCV bars for Tier C foundation (S.9.ohl-b).

Stores 1 row per (ts, ticker, timeframe) in market.ohlcv (V007 hypertable).
Forward accumulation with idempotent re-runs (ON CONFLICT DO NOTHING) per
ADR-007 D5 + D6 (10-day window each run, overlap safe).

Schema (V007):
- ts TIMESTAMPTZ NOT NULL
- ticker VARCHAR(32) NOT NULL
- timeframe VARCHAR(5) NOT NULL  -- "5m" | "15m" | "30m" | "1d" per ADR-007 D2
- open, high, low, close NUMERIC(14,6) NOT NULL
- volume BIGINT NULLABLE
- vwap NUMERIC(14,6) NULLABLE  -- always NULL (Schwab no provee, F-r4)
- PK (ts, ticker, timeframe)

Mirror IvSurfaceRepository S.7.surf-b executemany pattern for batch writes.
Uses PostgresPool.cursor() auto-commit wrapper (F-r9 catch: mirror
IvHistoryRepository/IvSurfaceRepository proven pattern, NOT raw
psycopg_pool.ConnectionPool.connection()+cursor() which loses commits).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class OhlcvRepository:
    """Repository for market.ohlcv writes + reads."""

    def __init__(self, pool) -> None:
        """Construct repository with shared PostgresPool wrapper.

        Args:
            pool: PostgresPool instance (shared_core.storage.postgres_pool).
                Type hint omitted to mirror IvHistoryRepository/IvSurfaceRepository
                convention (S.6.iv-b/S.7.surf-b).
        """
        self._pool = pool

    def write_bars(
        self,
        ticker: str,
        timeframe: str,
        bars: list[dict[str, Any]],
    ) -> int:
        """Batch INSERT bars idempotent.

        Args:
            ticker: Ticker symbol (e.g., "SPY").
            timeframe: "5m" | "15m" | "30m" | "1d" per ADR-007 D2.
            bars: List of dicts with keys ts (datetime tz-aware), open, high,
                low, close, volume (optional, may be None).

        Returns:
            Number of bars attempted (NOT inserted — ON CONFLICT may skip).

        Raises:
            ValueError: if any bar.ts is naive (no tzinfo).
        """
        if not bars:
            return 0

        for bar in bars:
            ts = bar.get("ts")
            if ts is None or ts.tzinfo is None:
                raise ValueError(
                    f"OhlcvRepository.write_bars: bar.ts must be tz-aware "
                    f"datetime, got {ts!r}"
                )

        rows = [
            (
                bar["ts"],
                ticker,
                timeframe,
                bar["open"],
                bar["high"],
                bar["low"],
                bar["close"],
                bar.get("volume"),
            )
            for bar in bars
        ]

        sql = """
            INSERT INTO market.ohlcv
                (ts, ticker, timeframe, open, high, low, close, volume)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (ts, ticker, timeframe) DO NOTHING
        """

        with self._pool.cursor() as cur:
            cur.executemany(sql, rows)

        return len(rows)

    def get_bars(
        self,
        ticker: str,
        timeframe: str,
        since: datetime,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Read bars for (ticker, timeframe) since timestamp, oldest first.

        Args:
            ticker: Ticker symbol.
            timeframe: "5m" | "15m" | "30m" | "1d".
            since: tz-aware lower bound (inclusive).
            limit: Max rows returned.

        Returns:
            List of dicts with keys ts, open, high, low, close, volume, vwap.

        Raises:
            ValueError: if since is naive.
        """
        if since.tzinfo is None:
            raise ValueError(
                f"OhlcvRepository.get_bars: since must be tz-aware, got {since!r}"
            )

        sql = """
            SELECT ts, open, high, low, close, volume, vwap
            FROM market.ohlcv
            WHERE ticker = %s AND timeframe = %s AND ts >= %s
            ORDER BY ts ASC
            LIMIT %s
        """

        with self._pool.cursor() as cur:
            cur.execute(sql, (ticker, timeframe, since, limit))
            rows = cur.fetchall()

        return [
            {
                "ts": row[0],
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
                "vwap": row[6],
            }
            for row in rows
        ]

    def count_for_ticker(self, ticker: str, timeframe: str) -> int:
        """Count rows for (ticker, timeframe). For validation + canary check.

        Args:
            ticker: Ticker symbol.
            timeframe: "5m" | "15m" | "30m" | "1d".

        Returns:
            Row count.
        """
        sql = """
            SELECT COUNT(*) FROM market.ohlcv
            WHERE ticker = %s AND timeframe = %s
        """

        with self._pool.cursor() as cur:
            cur.execute(sql, (ticker, timeframe))
            row = cur.fetchone()

        return int(row[0]) if row else 0

    def max_ts_for_ticker(
        self, ticker: str, timeframe: str
    ) -> datetime | None:
        """Return latest ts persisted for (ticker, timeframe), or None.

        Used by OhlcvWorker canary check (D-θ analog): skip if max_ts >= today
        21:30 UTC (already populated this run).
        """
        sql = """
            SELECT MAX(ts) FROM market.ohlcv
            WHERE ticker = %s AND timeframe = %s
        """

        with self._pool.cursor() as cur:
            cur.execute(sql, (ticker, timeframe))
            row = cur.fetchone()

        return row[0] if row and row[0] else None
