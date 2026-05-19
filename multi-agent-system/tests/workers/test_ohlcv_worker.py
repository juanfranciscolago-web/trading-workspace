"""Unit tests for OhlcvWorker (S.9.ohl-b).

Mock SchwabClient + OhlcvRepository pattern matching test_iv_history_worker.py
(S.6.iv-c proven precedent). asyncio_mode = "auto" en pyproject — async def
tests run sin @pytest.mark.asyncio decorator.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from multi_agent.data_layer.universe import TICKER_UNIVERSE
from multi_agent.workers.ohlcv_worker import (
    CANARY_TICKER,
    CANARY_TIMEFRAME,
    POLL_INTERVAL_S,
    SNAPSHOT_HOUR_UTC,
    SNAPSHOT_MINUTE_UTC,
    TIMEFRAMES,
    OhlcvWorker,
)


# Sample Schwab candle response (epoch_ms datetime + OHLCV per get_price_history)
_SAMPLE_CANDLES = [
    {
        "datetime": 1747688400000,  # 2025-05-19 21:00:00 UTC epoch_ms
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10_000,
    },
    {
        "datetime": 1747688700000,  # +5 min
        "open": 100.5,
        "high": 101.5,
        "low": 100.0,
        "close": 101.0,
        "volume": 12_000,
    },
]


# ── Fixture factory ──────────────────────────────────────────────────────────

def _make_worker(
    *,
    candles_response: list[dict] | None = None,
    max_ts: datetime | None = None,
    poll_interval_s: float = 0.05,
) -> tuple[OhlcvWorker, MagicMock, MagicMock]:
    """Build OhlcvWorker with mock repo + client.

    Returns (worker, mock_repo, mock_client). Defaults: 2-candle response,
    max_ts=None (canary missing → eligible to fetch).
    """
    mock_repo = MagicMock()
    mock_repo.max_ts_for_ticker.return_value = max_ts
    mock_repo.write_bars.return_value = 0  # default: 0 rows persisted

    mock_client = MagicMock()
    mock_client.get_price_history.return_value = (
        candles_response if candles_response is not None else _SAMPLE_CANDLES
    )

    worker = OhlcvWorker(
        repo=mock_repo,
        schwab_client=mock_client,
        poll_interval_s=poll_interval_s,
    )
    return worker, mock_repo, mock_client


def _patch_now(monkeypatch, fake_now: datetime) -> None:
    """Patch datetime.now in ohlcv_worker module to return fake_now."""
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fake_now.astimezone(tz) if tz else fake_now

    import multi_agent.workers.ohlcv_worker as worker_mod
    monkeypatch.setattr(worker_mod, "datetime", _FrozenDatetime)


# ── TestConstruction ─────────────────────────────────────────────────────────

class TestConstruction:
    """__init__ stores deps + applies poll_interval_s override."""

    def test_stores_repo_and_client(self):
        worker, repo, client = _make_worker()
        assert worker._repo is repo
        assert worker._client is client

    def test_default_poll_interval(self):
        repo = MagicMock()
        client = MagicMock()
        worker = OhlcvWorker(repo=repo, schwab_client=client)
        assert worker._poll == POLL_INTERVAL_S

    def test_override_poll_interval(self):
        repo = MagicMock()
        client = MagicMock()
        worker = OhlcvWorker(repo=repo, schwab_client=client, poll_interval_s=42.0)
        assert worker._poll == 42.0


# ── TestShouldFetchNow ───────────────────────────────────────────────────────

class TestShouldFetchNow:
    """_should_fetch_now() predicate — weekday + time + canary gates."""

    def test_skips_weekend_saturday(self, monkeypatch):
        worker, _, _ = _make_worker()
        saturday = datetime(2026, 5, 23, 22, 0, tzinfo=timezone.utc)  # Sat
        _patch_now(monkeypatch, saturday)

        assert worker._should_fetch_now() is False

    def test_skips_weekend_sunday(self, monkeypatch):
        worker, _, _ = _make_worker()
        sunday = datetime(2026, 5, 24, 22, 0, tzinfo=timezone.utc)  # Sun
        _patch_now(monkeypatch, sunday)

        assert worker._should_fetch_now() is False

    def test_skips_before_target_time(self, monkeypatch):
        worker, _, _ = _make_worker()
        weekday_early = datetime(2026, 5, 19, 20, 0, tzinfo=timezone.utc)  # Tue, before 21:30
        _patch_now(monkeypatch, weekday_early)

        assert worker._should_fetch_now() is False

    def test_skips_when_canary_already_populated(self, monkeypatch):
        weekday_post = datetime(2026, 5, 19, 22, 0, tzinfo=timezone.utc)  # Tue, after 21:30
        target_today = weekday_post.replace(
            hour=SNAPSHOT_HOUR_UTC, minute=SNAPSHOT_MINUTE_UTC, second=0, microsecond=0
        )
        worker, repo, _ = _make_worker(max_ts=target_today)
        _patch_now(monkeypatch, weekday_post)

        assert worker._should_fetch_now() is False
        repo.max_ts_for_ticker.assert_called_with(CANARY_TICKER, CANARY_TIMEFRAME)

    def test_returns_true_when_eligible(self, monkeypatch):
        weekday_post = datetime(2026, 5, 19, 22, 0, tzinfo=timezone.utc)  # Tue, after 21:30
        worker, _, _ = _make_worker(max_ts=None)  # canary missing
        _patch_now(monkeypatch, weekday_post)

        assert worker._should_fetch_now() is True


# ── TestFetchAllTickers ──────────────────────────────────────────────────────

class TestFetchAllTickers:
    """_fetch_all_tickers iterates 6 tickers × 4 timeframes con per-cell isolation."""

    async def test_iterates_24_cells(self):
        worker, repo, client = _make_worker()

        await worker._fetch_all_tickers()

        expected_cells = len(TICKER_UNIVERSE) * len(TIMEFRAMES)
        assert client.get_price_history.call_count == expected_cells
        assert repo.write_bars.call_count == expected_cells

    async def test_per_cell_error_isolation(self):
        """1 cell raise → other 23 still succeed (D-γ isolation)."""
        worker, repo, client = _make_worker()
        call_count = {"n": 0}

        def flaky_get_price_history(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first cell broken")
            return _SAMPLE_CANDLES

        client.get_price_history.side_effect = flaky_get_price_history

        # Must NOT raise — D-γ isolation catches per-cell exception
        await worker._fetch_all_tickers()

        expected_cells = len(TICKER_UNIVERSE) * len(TIMEFRAMES)
        assert client.get_price_history.call_count == expected_cells
        # 23 of 24 cells succeed → 23 write_bars calls
        assert repo.write_bars.call_count == expected_cells - 1


# ── TestFetchTickerTimeframe ─────────────────────────────────────────────────

class TestFetchTickerTimeframe:
    """_fetch_ticker_timeframe maps Schwab params + converts candles + persists."""

    def test_calls_schwab_with_5m_params(self):
        worker, _, client = _make_worker()

        worker._fetch_ticker_timeframe("SPY", "5m")

        client.get_price_history.assert_called_once_with(
            symbol="SPY",
            period_type="day",
            period=10,
            frequency_type="minute",
            frequency=5,
        )

    def test_calls_schwab_with_1d_params(self):
        worker, _, client = _make_worker()

        worker._fetch_ticker_timeframe("QQQ", "1d")

        client.get_price_history.assert_called_once_with(
            symbol="QQQ",
            period_type="day",
            period=10,
            frequency_type="daily",
            frequency=1,
        )

    def test_writes_bars_to_repo(self):
        worker, repo, _ = _make_worker()

        worker._fetch_ticker_timeframe("SPY", "5m")

        repo.write_bars.assert_called_once()
        args, _kwargs = repo.write_bars.call_args
        ticker, timeframe, bars = args
        assert ticker == "SPY"
        assert timeframe == "5m"
        assert len(bars) == 2
        assert bars[0]["open"] == 100.0
        assert bars[0]["volume"] == 10_000

    def test_skips_candles_without_datetime(self):
        broken = [{"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}]  # no datetime
        worker, repo, _ = _make_worker(candles_response=broken)

        worker._fetch_ticker_timeframe("SPY", "5m")

        # write_bars called with empty bars list (still 1 invocation, 0 rows)
        repo.write_bars.assert_called_once()
        _args, _ = repo.write_bars.call_args
        bars = _args[2]
        assert bars == []

    def test_volume_optional_persists_as_none(self):
        candles_no_volume = [{
            "datetime": 1747688400000,
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
        }]
        worker, repo, _ = _make_worker(candles_response=candles_no_volume)

        worker._fetch_ticker_timeframe("SPY", "5m")

        _args, _ = repo.write_bars.call_args
        bars = _args[2]
        assert bars[0]["volume"] is None


# ── TestEpochMsConversion ────────────────────────────────────────────────────

class TestEpochMsConversion:
    """_epoch_ms_to_datetime — F-r6 pattern reusable (UTC tz-aware)."""

    def test_returns_utc_aware_datetime(self):
        result = OhlcvWorker._epoch_ms_to_datetime(1747688400000)
        assert result.tzinfo is timezone.utc

    def test_correct_value(self):
        # 1747688400 = 2025-05-19 21:00:00 UTC
        result = OhlcvWorker._epoch_ms_to_datetime(1747688400000)
        expected = datetime(2025, 5, 19, 21, 0, 0, tzinfo=timezone.utc)
        assert result == expected


# ── TestShutdown ─────────────────────────────────────────────────────────────

class TestShutdown:
    """shutdown() signals stop_event."""

    def test_shutdown_sets_event(self):
        worker, _, _ = _make_worker()
        assert not worker._stop_event.is_set()

        worker.shutdown()

        assert worker._stop_event.is_set()
