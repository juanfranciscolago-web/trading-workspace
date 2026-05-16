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
