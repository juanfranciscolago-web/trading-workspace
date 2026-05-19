"""IvSurfaceRepository — daily options chain snapshots for iv_surface table (S.7.surf-b).

Stores per-contract IV + greeks + liquidity rows in market.iv_surface
(V007 hypertable, 1-day chunks). One snapshot run produces ~800-960 rows
per ticker (per Schwab strike_count=20 × ~10-12 expirations × 2 sides).

Forward accumulation only per ADR-006 D7 (mirror ADR-005 D9). Idempotent
writes via PK (ts, underlying, expiration, strike, option_type) + ON
CONFLICT DO NOTHING — safe for D7 recovery scenarios.

Pattern divergence from IvHistoryRepository:
- Batch INSERT via cursor.executemany (D-γ, new convention S.7.surf-b).
- Returns int rows inserted (D-β, vs None in iv_history).
- WRITE-only Sprint 7 per ADR-006 D6 (no read methods until Phase 2
  consumer surface lands).

Schwab chain → V007 column mappings (sub-decisions α-1 to α-3):
- strike: str "450.0" → float (F4 catch).
- contract["oi"] → open_interest column (F5 catch).
- chain key "calls"/"puts" → option_type "CALL"/"PUT" (F6 catch).
"""
from __future__ import annotations

import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)


# F6 mapping: Schwab chain plural keys → V007 option_type uppercase enum.
_OPTION_TYPE_MAP = {"calls": "CALL", "puts": "PUT"}


class IvSurfaceRepository:
    """Persistence for market.iv_surface hypertable (ADR-006 S.7.surf-b).

    Used by:
    - IvHistoryWorker (S.7.surf-c): write_chain_snapshot() at 21:15 UTC
      daily, alongside iv_history ATM scalar write. Per D3-1, surface
      write failure does NOT block iv_history success.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    def write_chain_snapshot(
        self,
        chain: dict,
        ticker: str,
        ts: datetime,
    ) -> int:
        """Insert all contracts in a Schwab chain as iv_surface rows.

        Iterates chain calls + puts × expirations × strikes, builds one
        row per contract, and writes via single executemany batch.
        Idempotent: ON CONFLICT (PK) DO NOTHING. Same (ts, ticker, ...)
        re-insert returns 0 rowcount (silent no-op).

        Args:
            chain: Schwab normalized chain dict (per S.5.6d shape):
                {"calls": {exp_str: {strike_str: contract_dict}}, "puts": ...}
                Strike is string per Schwab native format. Contract dict
                keys per S.5.6d: iv/delta/gamma/theta/vega/volume/oi/dte
                plus optional bid/ask/mark/last (latter NOT persisted —
                out of V007 scope, see ADR-006 D1).
            ticker: Underlying ticker (e.g., "SPY"). Stored in
                `underlying` column.
            ts: Snapshot timestamp (tz-aware, typically 21:15 UTC). MUST
                be tz-aware; ValueError if naive (defensive — naive ts
                corrupts hypertable time-range queries).

        Returns:
            Int count of rows actually inserted (cursor.rowcount post
            executemany). Excludes ON CONFLICT skips. 0 if chain empty.

        Raises:
            ValueError: If ts is naive (no tzinfo).

        Sub-decisions catch-driven (rule #15 pre-empt):
        - F4: strike key is string in chain ("450.0") → cast to float for
          NUMERIC(14,4) column.
        - F5: contract field "oi" → open_interest column (Schwab naming
          vs V007 column naming).
        - F6: chain key "calls"/"puts" plural lowercase → option_type
          "CALL"/"PUT" singular uppercase enum.
        - F7: V007 has `iv NOT NULL`. Skip contracts where iv falsy
          (None or 0) — invalid data, NOT to be persisted.
        """
        if ts.tzinfo is None:
            raise ValueError(f"ts must be timezone-aware, got naive: {ts}")

        rows: list[tuple] = []
        for option_type_key in ("calls", "puts"):
            option_type = _OPTION_TYPE_MAP[option_type_key]
            type_chain = chain.get(option_type_key, {})
            for exp_str, strikes in type_chain.items():
                expiration = date.fromisoformat(exp_str)
                for strike_str, contract in strikes.items():
                    iv = contract.get("iv")
                    if not iv:  # F7: skip if iv falsy (None or 0)
                        continue
                    rows.append((
                        ts,
                        ticker,
                        expiration,
                        float(strike_str),       # F4 cast
                        option_type,             # F6 mapping
                        iv,
                        contract.get("delta"),
                        contract.get("gamma"),
                        contract.get("theta"),
                        contract.get("vega"),
                        contract.get("oi"),      # F5 mapping → open_interest
                        contract.get("volume"),
                    ))

        if not rows:
            return 0  # Empty chain → no executemany call.

        with self._pool.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO market.iv_surface (
                    ts, underlying, expiration, strike, option_type,
                    iv, delta, gamma, theta, vega,
                    open_interest, volume
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ts, underlying, expiration, strike, option_type)
                DO NOTHING
                """,
                rows,
            )
            return cur.rowcount

    # ── READ methods (Phase 2 consumer surface, S.10.cons-b ADR-009 D3) ───────

    def get_surface_for_ticker(
        self,
        ticker: str,
        ts: datetime,
    ) -> list[dict]:
        """Return full surface rows para (ticker, ts).

        Used by SchwabDataLayer.snapshot() (S.10.cons-d) to populate
        TickerSnapshot.surface field. Returned dicts include all V007 columns
        excluding (ts, underlying) which are query constants.

        Args:
            ticker: Underlying symbol.
            ts: tz-aware timestamp (typically result of get_latest_surface).

        Returns:
            List of dicts con keys: expiration, strike, option_type, iv, delta,
            gamma, theta, vega, open_interest, volume. Ordered by expiration ASC,
            strike ASC, option_type ASC. Empty list if no rows.

        Raises:
            ValueError: si ts naive (defensive — naive ts queries hypertable
                con timezone confusion risk).
        """
        if ts.tzinfo is None:
            raise ValueError(
                f"IvSurfaceRepository.get_surface_for_ticker: ts must be tz-aware, "
                f"got {ts!r}"
            )

        sql = """
            SELECT expiration, strike, option_type, iv, delta, gamma, theta, vega,
                   open_interest, volume
            FROM market.iv_surface
            WHERE underlying = %s AND ts = %s
            ORDER BY expiration ASC, strike ASC, option_type ASC
        """

        with self._pool.cursor() as cur:
            cur.execute(sql, (ticker, ts))
            rows = cur.fetchall()

        return [
            {
                "expiration": row[0],
                "strike": row[1],
                "option_type": row[2],
                "iv": row[3],
                "delta": row[4],
                "gamma": row[5],
                "theta": row[6],
                "vega": row[7],
                "open_interest": row[8],
                "volume": row[9],
            }
            for row in rows
        ]

    def get_term_structure(
        self,
        ticker: str,
        ts: datetime,
    ) -> list[tuple[int, float]]:
        """Return term structure as list of (dte, weighted_avg_iv) tuples ordered.

        Phase 1 proxy (D3-1 sub-decision S.10.cons-b): weighted AVG(iv * open_interest)
        per expiration. OI concentrates at ATM strikes naturally en options markets,
        so weighted average proxies ATM IV without spot price lookup.

        Fallback COALESCE: si total OI=0 per expiration (edge case fresh bootstrap),
        falls back to plain AVG(iv).

        Future trigger ADR-009.X o ADR-010+: si paper trading signal degraded, add
        spot price column to market.iv_surface o cross-table join iv_history. NOT
        implemented Phase 1.

        Args:
            ticker: Underlying symbol.
            ts: tz-aware timestamp.

        Returns:
            List of (dte_days, atm_iv_proxy) tuples ordered front-to-back. dte_days
            computed as (expiration - ts.date()).days. Empty list if no data.

        Raises:
            ValueError: si ts naive.
        """
        if ts.tzinfo is None:
            raise ValueError(
                f"IvSurfaceRepository.get_term_structure: ts must be tz-aware, "
                f"got {ts!r}"
            )

        sql = """
            SELECT
                expiration,
                COALESCE(
                    SUM(iv * open_interest) / NULLIF(SUM(open_interest), 0),
                    AVG(iv)
                ) AS atm_iv_proxy
            FROM market.iv_surface
            WHERE underlying = %s AND ts = %s
            GROUP BY expiration
            ORDER BY expiration ASC
        """

        with self._pool.cursor() as cur:
            cur.execute(sql, (ticker, ts))
            rows = cur.fetchall()

        return [
            ((row[0] - ts.date()).days, float(row[1]))
            for row in rows
        ]

    def get_latest_surface(self, ticker: str) -> datetime | None:
        """Return latest ts available para ticker en iv_surface, o None.

        Used por SchwabDataLayer.snapshot() para identify most recent surface
        data persistent. Result feeds get_surface_for_ticker + get_term_structure
        consistent ts argument.

        Args:
            ticker: Underlying symbol.

        Returns:
            Latest ts (tz-aware UTC) si data exists, None si empty.
        """
        sql = """
            SELECT MAX(ts) FROM market.iv_surface
            WHERE underlying = %s
        """

        with self._pool.cursor() as cur:
            cur.execute(sql, (ticker,))
            row = cur.fetchone()

        return row[0] if row and row[0] else None
