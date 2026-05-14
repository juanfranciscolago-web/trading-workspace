"""IvHistoryRepository — daily ATM IV snapshots for iv_rank computation (S.6.iv-b).

Stores 1 row per (ticker, day) in market.iv_history (V018 hypertable).
Forward accumulation only per ADR-005 D9. Read pattern: get_history()
returns last N days for in-memory percentile compute (D8).

Idempotent writes via PK (ts, ticker) + ON CONFLICT DO NOTHING — safe
if IvHistoryWorker recovers + retries (D7 startup recovery check).
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class IvHistoryRepository:
    """Persistence for market.iv_history hypertable.

    Used by:
    - IvHistoryWorker (S.6.iv-c): write_snapshot() at 21:15 UTC daily.
    - SchwabDataLayer (S.6.iv-d): get_history() + count_for_ticker()
      for progressive disclosure threshold logic (D5).
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    def write_snapshot(
        self,
        ticker: str,
        ts: datetime,
        atm_iv: float,
        underlying_close: float | None = None,
    ) -> None:
        """Insert one daily snapshot row. Idempotent.

        Args:
            ticker: Ticker symbol (e.g., "SPY").
            ts: Snapshot timestamp (tz-aware, typically 21:15 UTC).
            atm_iv: ATM IV value (per D3 avg(call, put) at closest strike).
            underlying_close: Spot price at snapshot time (D-α audit field).

        Idempotent: ON CONFLICT (ts, ticker) DO NOTHING. Same (ticker, ts)
        inserted twice does NOT raise. Useful for D7 recovery scenarios.

        Raises:
            ValueError: If ts is naive (no tzinfo). Worker MUST produce
                tz-aware UTC timestamps; this defensive check prevents
                silent timezone confusion that would corrupt iv_rank
                window queries downstream.
        """
        if ts.tzinfo is None:
            raise ValueError(f"ts must be timezone-aware, got naive: {ts}")

        with self._pool.cursor() as cur:
            cur.execute(
                """
                INSERT INTO market.iv_history (ts, ticker, atm_iv, underlying_close)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ts, ticker) DO NOTHING
                """,
                (ts, ticker, atm_iv, underlying_close),
            )

    def get_history(
        self,
        ticker: str,
        days: int = 252,
    ) -> list[float]:
        """Return atm_iv values for the last `days` trading days, oldest first.

        Returned list is oldest→newest to match Eolo's _compute_iv_rank
        expected order (D8 formula port).

        Args:
            ticker: Ticker symbol to filter.
            days: Window size in trading days. Default 252 (~1 year).

        Returns:
            List of atm_iv floats. Empty list if no history. Length ≤ days.
        """
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT atm_iv
                FROM market.iv_history
                WHERE ticker = %s
                ORDER BY ts DESC
                LIMIT %s
                """,
                (ticker, days),
            )
            rows = cur.fetchall()
        # Reverse to oldest→newest order.
        return [float(row[0]) for row in reversed(rows)]

    def count_for_ticker(self, ticker: str) -> int:
        """Count of historical snapshots for a ticker.

        Used by SchwabDataLayer (S.6.iv-d) for D5 threshold check:
        - N < 10 → 50.0 placeholder
        - 10 ≤ N < 30 → percentile + WARNING
        - 30 ≤ N < 252 → percentile + INFO
        - N ≥ 252 → full percentile (no log)

        Args:
            ticker: Ticker symbol to filter.

        Returns:
            Integer count of rows in market.iv_history for this ticker.
        """
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM market.iv_history
                WHERE ticker = %s
                """,
                (ticker,),
            )
            result = cur.fetchone()
        return int(result[0]) if result else 0
