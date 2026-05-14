"""Unit tests for IvHistoryRepository (S.6.iv-b).

Mock pool + cursor pattern matching existing repository tests
(test_system_repository, test_llm_cost_repository).
No real DB hit — integration tests would belong en tests/db/ separate.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from multi_agent.persistence.iv_history_repository import IvHistoryRepository


# ── Fixture factory ──────────────────────────────────────────────────────────

def _make_pool_and_cursor() -> tuple[MagicMock, MagicMock]:
    """Build mock psycopg pool with cursor context manager.

    Cursor exposes execute / fetchall / fetchone. Tests configure return_value
    per test as needed (more flexible than pre-populated rows fixture).
    """
    cursor = MagicMock()
    pool = MagicMock()
    pool.cursor.return_value.__enter__.return_value = cursor
    pool.cursor.return_value.__exit__.return_value = None
    return pool, cursor


# ── TestWriteSnapshot ────────────────────────────────────────────────────────

class TestWriteSnapshot:
    """write_snapshot() — INSERT idempotent via PK + ON CONFLICT DO NOTHING."""

    def test_inserts_row_with_tz_aware_timestamp(self):
        pool, cursor = _make_pool_and_cursor()
        repo = IvHistoryRepository(pool)
        ts = datetime(2026, 5, 14, 21, 15, tzinfo=timezone.utc)

        repo.write_snapshot("SPY", ts, 0.185, underlying_close=450.0)

        assert cursor.execute.called
        sql, params = cursor.execute.call_args[0]
        assert "INSERT INTO market.iv_history" in sql
        assert "ON CONFLICT (ts, ticker) DO NOTHING" in sql
        assert params == (ts, "SPY", 0.185, 450.0)

    def test_accepts_none_for_underlying_close(self):
        pool, cursor = _make_pool_and_cursor()
        repo = IvHistoryRepository(pool)
        ts = datetime(2026, 5, 14, 21, 15, tzinfo=timezone.utc)

        repo.write_snapshot("QQQ", ts, 0.205)

        _, params = cursor.execute.call_args[0]
        assert params == (ts, "QQQ", 0.205, None)

    def test_raises_value_error_on_naive_datetime(self):
        pool, _ = _make_pool_and_cursor()
        repo = IvHistoryRepository(pool)
        naive_ts = datetime(2026, 5, 14, 21, 15)  # NO tzinfo

        with pytest.raises(ValueError, match="timezone-aware"):
            repo.write_snapshot("SPY", naive_ts, 0.18)

        # Cursor NOT entered — fail-loud before DB hit.
        pool.cursor.assert_not_called()


# ── TestGetHistory ───────────────────────────────────────────────────────────

class TestGetHistory:
    """get_history() — returns oldest→newest atm_iv list for last N days."""

    def test_returns_floats_oldest_to_newest(self):
        pool, cursor = _make_pool_and_cursor()
        # DB returns DESC order (newest first); repo reverses.
        cursor.fetchall.return_value = [
            (0.22,),  # newest
            (0.20,),
            (0.18,),  # oldest
        ]
        repo = IvHistoryRepository(pool)

        result = repo.get_history("SPY", days=3)

        assert result == [0.18, 0.20, 0.22]  # oldest first

        sql, params = cursor.execute.call_args[0]
        assert "ORDER BY ts DESC" in sql
        assert "LIMIT" in sql
        assert params == ("SPY", 3)

    def test_default_days_is_252(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = IvHistoryRepository(pool)

        repo.get_history("SPY")

        _, params = cursor.execute.call_args[0]
        assert params == ("SPY", 252)

    def test_empty_history_returns_empty_list(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = IvHistoryRepository(pool)

        result = repo.get_history("UNKNOWN", days=252)

        assert result == []

    def test_casts_decimal_to_float(self):
        # psycopg3 returns Decimal for NUMERIC columns.
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = [
            (Decimal("0.185000"),),
            (Decimal("0.200000"),),
        ]
        repo = IvHistoryRepository(pool)

        result = repo.get_history("SPY", days=2)

        assert all(isinstance(v, float) for v in result)
        assert result == [0.20, 0.185]  # reversed (oldest first)


# ── TestCountForTicker ───────────────────────────────────────────────────────

class TestCountForTicker:
    """count_for_ticker() — int count used by D5 threshold check."""

    def test_returns_count_as_int(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (42,)
        repo = IvHistoryRepository(pool)

        result = repo.count_for_ticker("SPY")

        assert result == 42
        assert isinstance(result, int)

        sql, params = cursor.execute.call_args[0]
        assert "SELECT COUNT(*)" in sql
        assert "FROM market.iv_history" in sql
        assert params == ("SPY",)

    def test_zero_when_no_history(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (0,)
        repo = IvHistoryRepository(pool)

        assert repo.count_for_ticker("UNKNOWN") == 0

    def test_handles_none_result_defensively(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = None  # Theoretical edge case
        repo = IvHistoryRepository(pool)

        assert repo.count_for_ticker("SPY") == 0


# ── TestHasSnapshotToday ─────────────────────────────────────────────────────

class TestHasSnapshotToday:
    """has_snapshot_today() — D-θ canary check used by IvHistoryWorker."""

    def test_returns_true_when_row_exists(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (1,)
        repo = IvHistoryRepository(pool)

        result = repo.has_snapshot_today("SPY", date(2026, 5, 14))

        assert result is True
        sql, params = cursor.execute.call_args[0]
        assert "SELECT 1 FROM market.iv_history" in sql
        assert "DATE(ts) = %s" in sql
        assert "LIMIT 1" in sql
        assert params == ("SPY", date(2026, 5, 14))

    def test_returns_false_when_no_row(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = None
        repo = IvHistoryRepository(pool)

        assert repo.has_snapshot_today("SPY", date(2026, 5, 14)) is False
