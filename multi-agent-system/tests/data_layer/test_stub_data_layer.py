"""
Unit tests for StubDataLayer.

Three groups: determinism, shape, ranges.
No external deps — pure stdlib + the package under test.
"""
from __future__ import annotations

import json

import pytest

from multi_agent.data_layer import (
    MarketState,
    StubDataLayer,
    TICKER_UNIVERSE,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def state() -> MarketState:
    """Single snapshot from default seed."""
    return StubDataLayer().snapshot()


@pytest.fixture
def state_pair() -> tuple[MarketState, MarketState]:
    """Two snapshots from the same seed (1234)."""
    return (
        StubDataLayer(seed=1234).snapshot(),
        StubDataLayer(seed=1234).snapshot(),
    )


# ── Group 1: Determinism ──────────────────────────────────────────────────────

class TestDeterminism:

    def test_same_seed_produces_same_per_ticker_data(self, state_pair):
        s1, s2 = state_pair
        assert s1.tickers.keys() == s2.tickers.keys()
        for ticker in s1.tickers:
            # Frozen dataclass equality compares all nested fields
            assert s1.tickers[ticker] == s2.tickers[ticker], f"{ticker} differs"

    def test_same_seed_produces_same_correlations(self, state_pair):
        s1, s2 = state_pair
        assert s1.correlations == s2.correlations

    def test_different_seeds_produce_different_per_ticker_data(self):
        s1 = StubDataLayer(seed=1).snapshot()
        s2 = StubDataLayer(seed=99).snapshot()
        differs = any(
            s1.tickers[t].ohlcv_daily != s2.tickers[t].ohlcv_daily
            for t in s1.tickers
        )
        assert differs


# ── Group 2: Shape ────────────────────────────────────────────────────────────

class TestShape:

    def test_universe_has_six_tickers(self, state):
        assert set(state.tickers.keys()) == set(TICKER_UNIVERSE.keys())
        assert len(state.tickers) == 6

    def test_each_ticker_has_60_daily_bars(self, state):
        for ticker, snapshot in state.tickers.items():
            assert len(snapshot.ohlcv_daily) == 60, (
                f"{ticker} has {len(snapshot.ohlcv_daily)} daily bars"
            )

    def test_each_ticker_has_24_hourly_bars(self, state):
        for ticker, snapshot in state.tickers.items():
            assert len(snapshot.ohlcv_hourly) == 24, (
                f"{ticker} has {len(snapshot.ohlcv_hourly)} hourly bars"
            )

    def test_correlations_has_15_pairs(self, state):
        # C(6, 2) = 15
        assert len(state.correlations) == 15

    def test_to_dict_is_json_serializable(self, state):
        d = state.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert len(json_str) > 0

    def test_to_dict_correlations_keys_are_strings(self, state):
        d = state.to_dict()
        for key in d["correlations"]:
            assert isinstance(key, str)
            assert "_" in key  # format "A_B"


# ── Group 3: Ranges ───────────────────────────────────────────────────────────

class TestRanges:

    def test_iv_rank_in_zero_to_hundred(self, state):
        for ticker, snapshot in state.tickers.items():
            assert 0.0 <= snapshot.iv_rank <= 100.0, (
                f"{ticker} iv_rank={snapshot.iv_rank}"
            )

    def test_iv_percentile_in_zero_to_hundred(self, state):
        for ticker, snapshot in state.tickers.items():
            assert 0.0 <= snapshot.iv_percentile <= 100.0, (
                f"{ticker} iv_percentile={snapshot.iv_percentile}"
            )

    def test_correlations_in_minus_one_to_one(self, state):
        for pair, value in state.correlations.items():
            assert -1.0 <= value <= 1.0, f"{pair}={value}"

    def test_last_price_positive(self, state):
        for ticker, snapshot in state.tickers.items():
            assert snapshot.last_price > 0, (
                f"{ticker} last_price={snapshot.last_price}"
            )

    def test_realized_vol_30d_positive(self, state):
        for ticker, snapshot in state.tickers.items():
            assert snapshot.realized_vol_30d > 0, (
                f"{ticker} realized_vol_30d={snapshot.realized_vol_30d}"
            )

    def test_ohlcv_high_low_consistency(self, state):
        for ticker, snapshot in state.tickers.items():
            for bar in snapshot.ohlcv_daily + snapshot.ohlcv_hourly:
                assert bar.high >= max(bar.open, bar.close), (
                    f"{ticker} high={bar.high} < max(o,c)"
                )
                assert bar.low <= min(bar.open, bar.close), (
                    f"{ticker} low={bar.low} > min(o,c)"
                )

    def test_ohlcv_daily_timestamps_ascending(self, state):
        for ticker, snapshot in state.tickers.items():
            timestamps = [bar.timestamp for bar in snapshot.ohlcv_daily]
            assert timestamps == sorted(timestamps), (
                f"{ticker} daily timestamps not ascending"
            )

    def test_ohlcv_hourly_timestamps_ascending(self, state):
        for ticker, snapshot in state.tickers.items():
            timestamps = [bar.timestamp for bar in snapshot.ohlcv_hourly]
            assert timestamps == sorted(timestamps), (
                f"{ticker} hourly timestamps not ascending"
            )

    def test_skew_put_bias(self, state):
        """Put skew IV should be greater than ATM IV (puts pricier than ATM)."""
        for ticker, snapshot in state.tickers.items():
            assert snapshot.skew.put_skew_iv > snapshot.skew.atm_iv, (
                f"{ticker} put_skew_iv={snapshot.skew.put_skew_iv} "
                f"<= atm_iv={snapshot.skew.atm_iv}"
            )
