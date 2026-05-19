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


# ── READ methods tests (Phase 2 consumer surface, S.10.cons-b ADR-009 D3) ─────


class TestGetSurfaceForTicker:
    """get_surface_for_ticker() — returns ordered list[dict] full surface rows."""

    def test_returns_full_rows(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = [
            (date(2026, 6, 19), 450.0, "CALL", 0.20, 0.50, 0.05, -0.04, 0.12, 8000, 1500),
            (date(2026, 6, 19), 450.0, "PUT",  0.21, -0.50, 0.05, -0.04, 0.12, 6000, 1200),
            (date(2026, 7, 17), 455.0, "CALL", 0.22, 0.30, 0.04, -0.03, 0.10, 4000, 800),
        ]
        repo = IvSurfaceRepository(pool)

        result = repo.get_surface_for_ticker("SPY", _TS)

        assert len(result) == 3
        assert result[0]["expiration"] == date(2026, 6, 19)
        assert result[0]["strike"] == 450.0
        assert result[0]["option_type"] == "CALL"
        assert result[0]["iv"] == 0.20
        assert result[0]["open_interest"] == 8000
        assert result[0]["volume"] == 1500
        # Verify all 10 expected keys present
        expected_keys = {"expiration", "strike", "option_type", "iv", "delta",
                        "gamma", "theta", "vega", "open_interest", "volume"}
        assert set(result[0].keys()) == expected_keys

    def test_orders_by_exp_strike_type(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = IvSurfaceRepository(pool)

        repo.get_surface_for_ticker("SPY", _TS)

        sql, _ = cursor.execute.call_args[0]
        assert "ORDER BY expiration ASC, strike ASC, option_type ASC" in sql

    def test_filters_by_ticker_and_ts(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = IvSurfaceRepository(pool)

        repo.get_surface_for_ticker("QQQ", _TS)

        sql, params = cursor.execute.call_args[0]
        assert "WHERE underlying = %s AND ts = %s" in sql
        assert params == ("QQQ", _TS)

    def test_empty_result(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = IvSurfaceRepository(pool)

        result = repo.get_surface_for_ticker("UNKNOWN", _TS)

        assert result == []

    def test_raises_on_naive_ts(self):
        pool, _ = _make_pool_and_cursor()
        repo = IvSurfaceRepository(pool)
        naive_ts = datetime(2026, 5, 16, 21, 15)  # NO tzinfo

        with pytest.raises(ValueError, match="tz-aware"):
            repo.get_surface_for_ticker("SPY", naive_ts)

        pool.cursor.assert_not_called()


class TestGetTermStructure:
    """get_term_structure() — weighted AVG(iv * OI) proxy per expiration."""

    def test_returns_dte_iv_tuples(self):
        pool, cursor = _make_pool_and_cursor()
        # ts = 2026-05-16 → dte for 2026-06-19 = 34, for 2026-07-17 = 62
        cursor.fetchall.return_value = [
            (date(2026, 6, 19), 0.205),
            (date(2026, 7, 17), 0.225),
        ]
        repo = IvSurfaceRepository(pool)

        result = repo.get_term_structure("SPY", _TS)

        assert len(result) == 2
        assert result[0] == (34, 0.205)
        assert result[1] == (62, 0.225)

    def test_orders_by_expiration_ascending(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = IvSurfaceRepository(pool)

        repo.get_term_structure("SPY", _TS)

        sql, _ = cursor.execute.call_args[0]
        assert "ORDER BY expiration ASC" in sql

    def test_uses_weighted_avg_with_coalesce(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = IvSurfaceRepository(pool)

        repo.get_term_structure("SPY", _TS)

        sql, _ = cursor.execute.call_args[0]
        assert "COALESCE" in sql
        assert "SUM(iv * open_interest)" in sql
        assert "NULLIF(SUM(open_interest), 0)" in sql
        assert "AVG(iv)" in sql  # fallback branch

    def test_empty_result(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = IvSurfaceRepository(pool)

        result = repo.get_term_structure("SPY", _TS)

        assert result == []

    def test_raises_on_naive_ts(self):
        pool, _ = _make_pool_and_cursor()
        repo = IvSurfaceRepository(pool)
        naive_ts = datetime(2026, 5, 16, 21, 15)

        with pytest.raises(ValueError, match="tz-aware"):
            repo.get_term_structure("SPY", naive_ts)

        pool.cursor.assert_not_called()


class TestGetLatestSurface:
    """get_latest_surface() — MAX(ts) per ticker, None if empty."""

    def test_returns_max_ts(self):
        pool, cursor = _make_pool_and_cursor()
        latest = datetime(2026, 5, 16, 21, 15, tzinfo=timezone.utc)
        cursor.fetchone.return_value = (latest,)
        repo = IvSurfaceRepository(pool)

        result = repo.get_latest_surface("SPY")

        assert result == latest

    def test_returns_none_when_empty(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (None,)
        repo = IvSurfaceRepository(pool)

        result = repo.get_latest_surface("SPY")

        assert result is None

    def test_returns_none_when_no_row(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = None
        repo = IvSurfaceRepository(pool)

        result = repo.get_latest_surface("SPY")

        assert result is None

    def test_filters_by_ticker(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (None,)
        repo = IvSurfaceRepository(pool)

        repo.get_latest_surface("QQQ")

        sql, params = cursor.execute.call_args[0]
        assert "MAX(ts)" in sql
        assert "WHERE underlying = %s" in sql
        assert params == ("QQQ",)

    def test_does_not_validate_ts(self):
        """get_latest_surface takes only ticker — no ts arg → no ValueError path."""
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (None,)
        repo = IvSurfaceRepository(pool)

        # No exception raised on any ticker string
        result = repo.get_latest_surface("SPY")
        assert result is None
