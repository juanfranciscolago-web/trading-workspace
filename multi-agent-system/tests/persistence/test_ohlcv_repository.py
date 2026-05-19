"""Unit tests for OhlcvRepository (S.9.ohl-b).

Mock pool + cursor pattern matching test_iv_history_repository.py +
test_iv_surface_repository.py (S.6.iv-b + S.7.surf-b proven precedent).
Auto-commit cursor wrapper via PostgresPool.cursor() (F-r9 fix).
No real DB hit — integration tests would belong en tests/db/ separate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from multi_agent.persistence.ohlcv_repository import OhlcvRepository


# ── Fixture factory ──────────────────────────────────────────────────────────

def _make_pool_and_cursor() -> tuple[MagicMock, MagicMock]:
    """Build mock psycopg pool with cursor context manager.

    Mirror IvHistoryRepository / IvSurfaceRepository factory. Cursor exposes
    execute / executemany / fetchall / fetchone — tests configure return_value
    per test as needed.
    """
    cursor = MagicMock()
    pool = MagicMock()
    pool.cursor.return_value.__enter__.return_value = cursor
    pool.cursor.return_value.__exit__.return_value = None
    return pool, cursor


def _bar(ts: datetime, open_=100.0, high=101.0, low=99.0, close=100.5, volume=10_000):
    """Helper to build a bar dict with sane defaults."""
    return {
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


# ── TestWriteBars ────────────────────────────────────────────────────────────

class TestWriteBars:
    """write_bars() — batch INSERT idempotent via executemany + ON CONFLICT."""

    def test_inserts_rows_via_executemany(self):
        pool, cursor = _make_pool_and_cursor()
        repo = OhlcvRepository(pool)
        ts = datetime(2026, 5, 19, 21, 30, tzinfo=timezone.utc)
        bars = [_bar(ts), _bar(ts.replace(minute=35))]

        n = repo.write_bars("SPY", "5m", bars)

        assert n == 2
        assert cursor.executemany.called
        sql, rows = cursor.executemany.call_args[0]
        assert "INSERT INTO market.ohlcv" in sql
        assert "ON CONFLICT (ts, ticker, timeframe) DO NOTHING" in sql
        assert len(rows) == 2
        # Row tuple shape: (ts, ticker, timeframe, open, high, low, close, volume)
        assert rows[0] == (
            bars[0]["ts"], "SPY", "5m",
            bars[0]["open"], bars[0]["high"], bars[0]["low"], bars[0]["close"],
            bars[0]["volume"],
        )

    def test_idempotent_on_repeated_call(self):
        """Same bars inserted twice — repo does NOT raise; DB ON CONFLICT handles dedup."""
        pool, cursor = _make_pool_and_cursor()
        repo = OhlcvRepository(pool)
        ts = datetime(2026, 5, 19, 21, 30, tzinfo=timezone.utc)
        bars = [_bar(ts)]

        repo.write_bars("SPY", "5m", bars)
        repo.write_bars("SPY", "5m", bars)  # re-fire

        assert cursor.executemany.call_count == 2

    def test_empty_bars_returns_zero_no_db_call(self):
        pool, _ = _make_pool_and_cursor()
        repo = OhlcvRepository(pool)

        n = repo.write_bars("SPY", "5m", [])

        assert n == 0
        pool.cursor.assert_not_called()

    def test_raises_value_error_on_naive_ts(self):
        pool, _ = _make_pool_and_cursor()
        repo = OhlcvRepository(pool)
        naive_ts = datetime(2026, 5, 19, 21, 30)  # NO tzinfo
        bars = [_bar(naive_ts)]

        with pytest.raises(ValueError, match="tz-aware"):
            repo.write_bars("SPY", "5m", bars)

        # Fail-loud before DB hit
        pool.cursor.assert_not_called()

    def test_volume_optional_persists_as_none(self):
        pool, cursor = _make_pool_and_cursor()
        repo = OhlcvRepository(pool)
        ts = datetime(2026, 5, 19, 21, 30, tzinfo=timezone.utc)
        bar = {"ts": ts, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5}
        # volume key missing entirely

        repo.write_bars("SPY", "5m", [bar])

        _, rows = cursor.executemany.call_args[0]
        assert rows[0][7] is None  # volume slot in tuple


# ── TestGetBars ──────────────────────────────────────────────────────────────

class TestGetBars:
    """get_bars() — historical query ASC order with limit + since filter."""

    def test_returns_dicts_oldest_first(self):
        pool, cursor = _make_pool_and_cursor()
        ts1 = datetime(2026, 5, 19, 21, 30, tzinfo=timezone.utc)
        ts2 = datetime(2026, 5, 19, 21, 35, tzinfo=timezone.utc)
        cursor.fetchall.return_value = [
            (ts1, 100.0, 101.0, 99.0, 100.5, 10_000, None),
            (ts2, 100.5, 102.0, 100.0, 101.5, 12_000, None),
        ]
        repo = OhlcvRepository(pool)

        result = repo.get_bars("SPY", "5m", since=ts1)

        assert len(result) == 2
        assert result[0]["ts"] == ts1
        assert result[0]["open"] == 100.0
        assert result[1]["close"] == 101.5

    def test_sql_filters_ticker_timeframe_since_limit(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = OhlcvRepository(pool)
        since = datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc)

        repo.get_bars("QQQ", "1d", since=since, limit=42)

        sql, params = cursor.execute.call_args[0]
        assert "WHERE ticker = %s AND timeframe = %s AND ts >= %s" in sql
        assert "ORDER BY ts ASC" in sql
        assert params == ("QQQ", "1d", since, 42)

    def test_raises_value_error_on_naive_since(self):
        pool, _ = _make_pool_and_cursor()
        repo = OhlcvRepository(pool)
        naive_since = datetime(2026, 5, 19, 0, 0)

        with pytest.raises(ValueError, match="tz-aware"):
            repo.get_bars("SPY", "5m", since=naive_since)

        pool.cursor.assert_not_called()

    def test_empty_result_returns_empty_list(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = []
        repo = OhlcvRepository(pool)
        since = datetime(2026, 5, 19, 0, 0, tzinfo=timezone.utc)

        assert repo.get_bars("UNKNOWN", "5m", since=since) == []


# ── TestCountForTicker ───────────────────────────────────────────────────────

class TestCountForTicker:
    """count_for_ticker() — row count filtered by (ticker, timeframe)."""

    def test_returns_zero_when_empty(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (0,)
        repo = OhlcvRepository(pool)

        assert repo.count_for_ticker("SPY", "5m") == 0

    def test_filters_ticker_and_timeframe(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (3,)
        repo = OhlcvRepository(pool)

        result = repo.count_for_ticker("SPY", "5m")

        assert result == 3
        sql, params = cursor.execute.call_args[0]
        assert "WHERE ticker = %s AND timeframe = %s" in sql
        assert params == ("SPY", "5m")

    def test_returns_zero_when_fetchone_none(self):
        """Defensive: fetchone returning None should yield 0, not crash."""
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = None
        repo = OhlcvRepository(pool)

        assert repo.count_for_ticker("SPY", "5m") == 0


# ── TestMaxTsForTicker ───────────────────────────────────────────────────────

class TestMaxTsForTicker:
    """max_ts_for_ticker() — canary check for OhlcvWorker D-θ analog."""

    def test_returns_none_when_empty(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (None,)
        repo = OhlcvRepository(pool)

        assert repo.max_ts_for_ticker("SPY", "1d") is None

    def test_returns_latest_ts(self):
        pool, cursor = _make_pool_and_cursor()
        latest = datetime(2026, 5, 19, 21, 30, tzinfo=timezone.utc)
        cursor.fetchone.return_value = (latest,)
        repo = OhlcvRepository(pool)

        assert repo.max_ts_for_ticker("SPY", "1d") == latest

    def test_filters_by_ticker_and_timeframe(self):
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchone.return_value = (None,)
        repo = OhlcvRepository(pool)

        repo.max_ts_for_ticker("QQQ", "5m")

        sql, params = cursor.execute.call_args[0]
        assert "MAX(ts)" in sql
        assert "WHERE ticker = %s AND timeframe = %s" in sql
        assert params == ("QQQ", "5m")
