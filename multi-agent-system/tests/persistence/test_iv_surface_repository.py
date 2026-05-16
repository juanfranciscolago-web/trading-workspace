"""Unit tests for IvSurfaceRepository (S.7.surf-b).

Mock pool + cursor pattern matching IvHistoryRepository tests (S.6.iv-b).
No real DB hit — integration tests would belong en tests/db/ separate.

Coverage map per ADR-006 decisions + F4-F7 catches:
- write_chain_snapshot happy path + variants.
- F4 strike string→float cast.
- F5 contract["oi"] → open_interest column mapping.
- F6 calls/puts plural lowercase → CALL/PUT uppercase enum.
- F7 falsy iv guard (skip None/0).
- D-β int rowcount return.
- D-γ executemany batch.
- D-δ ON CONFLICT DO NOTHING idempotency.
- Defensive: naive datetime ValueError + empty chain.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from multi_agent.persistence.iv_surface_repository import IvSurfaceRepository


# ── Fixture factory ──────────────────────────────────────────────────────────

def _make_pool_and_cursor() -> tuple[MagicMock, MagicMock]:
    """Build mock psycopg pool with cursor context manager.

    Cursor exposes executemany / rowcount. Tests configure rowcount
    per test as needed.
    """
    cursor = MagicMock()
    pool = MagicMock()
    pool.cursor.return_value.__enter__.return_value = cursor
    pool.cursor.return_value.__exit__.return_value = None
    return pool, cursor


def _make_minimal_chain() -> dict:
    """Minimal chain fixture: 1 expiration × 1 strike × call+put. 2 contracts."""
    return {
        "calls": {
            "2026-06-19": {
                "450.0": {
                    "iv": 0.20, "delta": 0.50, "gamma": 0.05,
                    "theta": -0.04, "vega": 0.12,
                    "volume": 1500, "oi": 8000, "dte": 30,
                },
            },
        },
        "puts": {
            "2026-06-19": {
                "450.0": {
                    "iv": 0.21, "delta": -0.50, "gamma": 0.05,
                    "theta": -0.04, "vega": 0.12,
                    "volume": 1200, "oi": 6000, "dte": 30,
                },
            },
        },
        "expirations": ["2026-06-19"],
    }


_TS = datetime(2026, 5, 16, 21, 15, tzinfo=timezone.utc)


# ── TestWriteChainSnapshot ───────────────────────────────────────────────────

class TestWriteChainSnapshot:
    """write_chain_snapshot() — executemany batch INSERT idempotent."""

    def test_inserts_rows_for_chain_with_calls_and_puts(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.rowcount = 2
        repo = IvSurfaceRepository(pool)

        result = repo.write_chain_snapshot(_make_minimal_chain(), "SPY", _TS)

        assert result == 2
        assert cursor.executemany.called
        sql, rows = cursor.executemany.call_args[0]
        assert "INSERT INTO market.iv_surface" in sql
        assert len(rows) == 2

    def test_strike_string_cast_to_float(self):
        """F4: chain strike key is str '450.0' → must cast to float."""
        pool, cursor = _make_pool_and_cursor()
        cursor.rowcount = 1
        repo = IvSurfaceRepository(pool)

        chain = {
            "calls": {"2026-06-19": {"450.0": {"iv": 0.20}}},
            "puts": {},
        }
        repo.write_chain_snapshot(chain, "SPY", _TS)

        _, rows = cursor.executemany.call_args[0]
        # row tuple: (ts, ticker, expiration, strike, option_type, iv, ...)
        strike_value = rows[0][3]
        assert isinstance(strike_value, float)
        assert strike_value == 450.0

    def test_field_name_oi_mapped_to_open_interest(self):
        """F5: contract['oi'] → open_interest column (position 10 in tuple)."""
        pool, cursor = _make_pool_and_cursor()
        cursor.rowcount = 1
        repo = IvSurfaceRepository(pool)

        chain = {
            "calls": {"2026-06-19": {"450.0": {"iv": 0.20, "oi": 8000}}},
            "puts": {},
        }
        repo.write_chain_snapshot(chain, "SPY", _TS)

        _, rows = cursor.executemany.call_args[0]
        # row: (ts, ticker, exp, strike, type, iv, delta, gamma, theta, vega, OI, volume)
        open_interest_value = rows[0][10]
        assert open_interest_value == 8000

    def test_option_type_normalized_to_uppercase(self):
        """F6: 'calls'/'puts' plural lowercase → 'CALL'/'PUT' singular."""
        pool, cursor = _make_pool_and_cursor()
        cursor.rowcount = 2
        repo = IvSurfaceRepository(pool)

        repo.write_chain_snapshot(_make_minimal_chain(), "SPY", _TS)

        _, rows = cursor.executemany.call_args[0]
        # row position 4 = option_type
        option_types = {row[4] for row in rows}
        assert option_types == {"CALL", "PUT"}

    def test_skips_contract_with_falsy_iv(self):
        """F7: iv=None or iv=0 → skip contract (V007 iv NOT NULL)."""
        pool, cursor = _make_pool_and_cursor()
        cursor.rowcount = 1
        repo = IvSurfaceRepository(pool)

        chain = {
            "calls": {
                "2026-06-19": {
                    "450.0": {"iv": 0.20},        # valid → include
                    "460.0": {"iv": 0.0},          # falsy → skip
                    "470.0": {"iv": None},         # None → skip
                },
            },
            "puts": {},
        }
        repo.write_chain_snapshot(chain, "SPY", _TS)

        _, rows = cursor.executemany.call_args[0]
        assert len(rows) == 1  # Only the iv=0.20 contract.
        assert rows[0][5] == 0.20  # row position 5 = iv

    def test_handles_missing_greek_fields_as_null(self):
        """F7 NULL handling: contract.get(field) → None acceptable for non-NOT-NULL columns."""
        pool, cursor = _make_pool_and_cursor()
        cursor.rowcount = 1
        repo = IvSurfaceRepository(pool)

        chain = {
            "calls": {
                "2026-06-19": {
                    "450.0": {"iv": 0.20},  # no greeks/oi/volume fields
                },
            },
            "puts": {},
        }
        repo.write_chain_snapshot(chain, "SPY", _TS)

        _, rows = cursor.executemany.call_args[0]
        row = rows[0]
        # Positions 6-11 (delta, gamma, theta, vega, oi, volume) all None.
        assert all(v is None for v in row[6:12])

    def test_uses_executemany_for_batch(self):
        """D-γ: cursor.executemany called once for batch (not multiple execute calls)."""
        pool, cursor = _make_pool_and_cursor()
        cursor.rowcount = 2
        repo = IvSurfaceRepository(pool)

        repo.write_chain_snapshot(_make_minimal_chain(), "SPY", _TS)

        assert cursor.executemany.call_count == 1
        assert cursor.execute.call_count == 0  # NOT individual execute calls.

    def test_on_conflict_do_nothing_idempotent(self):
        """D-δ: ON CONFLICT (PK) DO NOTHING for recovery idempotency."""
        pool, cursor = _make_pool_and_cursor()
        cursor.rowcount = 2
        repo = IvSurfaceRepository(pool)

        repo.write_chain_snapshot(_make_minimal_chain(), "SPY", _TS)

        sql, _ = cursor.executemany.call_args[0]
        assert "ON CONFLICT (ts, underlying, expiration, strike, option_type)" in sql
        assert "DO NOTHING" in sql

    def test_raises_value_error_on_naive_datetime(self):
        """Defensive: naive ts corrupts hypertable time-range queries."""
        pool, _ = _make_pool_and_cursor()
        repo = IvSurfaceRepository(pool)
        naive_ts = datetime(2026, 5, 16, 21, 15)  # NO tzinfo

        with pytest.raises(ValueError, match="timezone-aware"):
            repo.write_chain_snapshot(_make_minimal_chain(), "SPY", naive_ts)

        # Cursor NOT entered — fail-loud before DB hit.
        pool.cursor.assert_not_called()

    def test_returns_int_rows_inserted(self):
        """D-β: returns cursor.rowcount as int (excludes ON CONFLICT skips)."""
        pool, cursor = _make_pool_and_cursor()
        cursor.rowcount = 5  # 5 of N inserted, rest were conflicts
        repo = IvSurfaceRepository(pool)

        result = repo.write_chain_snapshot(_make_minimal_chain(), "SPY", _TS)

        assert result == 5
        assert isinstance(result, int)

    def test_empty_chain_returns_zero_no_executemany(self):
        """Defensive: empty/missing chain → no executemany call, return 0."""
        pool, cursor = _make_pool_and_cursor()
        repo = IvSurfaceRepository(pool)

        result = repo.write_chain_snapshot({"calls": {}, "puts": {}}, "SPY", _TS)

        assert result == 0
        cursor.executemany.assert_not_called()
        pool.cursor.assert_not_called()  # Pool not even entered.
