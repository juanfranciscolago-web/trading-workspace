"""
Unit tests for SchwabDataLayer.

Mocking strategy (simpler than tests/brokers/):
    - SchwabClient is fully mocked (duck-typed input to __init__).
    - mock_client.get_price_history.return_value = list of Schwab-format candles.
    - mock_client.get_options_chain.return_value = normalized chain dict.
    - No httpx / no GCP patches — client mock isolates SchwabDataLayer logic.

Helper factory `_build_layer_with_mocks()` returns (layer, mock_client).
Module-level _make_candles helper generates Schwab-format candle lists.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import exp
from unittest.mock import MagicMock

import pytest

from multi_agent.data_layer import (
    OHLCV,
    SchwabDataLayer,
    TICKER_UNIVERSE,
)
from multi_agent.data_layer.interfaces import MarketState
from shared_core.brokers.schwab_client import SchwabAPIError


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_candles(
    n_days: int = 60,
    start_close: float = 440.0,
    daily_return_pct: float = 0.001,
) -> list[dict]:
    """Build n_days Schwab-format candle dicts with monotonic epoch_ms
    timestamps and geometric returns of `daily_return_pct` per day.
    """
    candles = []
    close = start_close
    base_ts_ms = 1_700_000_000_000   # arbitrary fixed start (2023-11-14 UTC)
    for i in range(n_days):
        ts_ms = base_ts_ms + i * 86_400_000   # +1 day per bar
        open_price = close
        new_close = close * (1 + daily_return_pct)
        candles.append({
            "datetime": ts_ms,
            "open":   round(open_price, 2),
            "high":   round(max(open_price, new_close) * 1.005, 2),
            "low":    round(min(open_price, new_close) * 0.995, 2),
            "close":  round(new_close, 2),
            "volume": 1_000_000,
        })
        close = new_close
    return candles


# Normalized chain (output shape of SchwabClient.get_options_chain).
# Two expirations: 30 DTE (in range 30±15) + 58 DTE (out of range).
_SAMPLE_CHAIN_RESPONSE = {
    "underlying": "SPY",
    "ts": 1714867200.0,
    "spot": {
        "last": 450.0, "bid": 449.95, "ask": 450.05,
        "mark": 450.0, "volatility": 0.18,
    },
    "calls": {
        "2026-06-19": {
            "440.0": {"bid": 12.0, "ask": 12.2, "mark": 12.1, "last": 12.1,
                      "iv": 0.18, "delta": 0.75, "gamma": 0.04,
                      "theta": -0.03, "vega": 0.10,
                      "volume": 500, "oi": 2000, "dte": 30},
            "450.0": {"bid": 5.0,  "ask": 5.2,  "mark": 5.1,  "last": 5.12,
                      "iv": 0.20, "delta": 0.50, "gamma": 0.05,
                      "theta": -0.04, "vega": 0.12,
                      "volume": 1500, "oi": 8000, "dte": 30},
            "460.0": {"bid": 2.0,  "ask": 2.2,  "mark": 2.1,  "last": 2.1,
                      "iv": 0.22, "delta": 0.25, "gamma": 0.04,
                      "theta": -0.04, "vega": 0.10,
                      "volume": 800, "oi": 4000, "dte": 30},
            "470.0": {"bid": 0.5,  "ask": 0.7,  "mark": 0.6,  "last": 0.6,
                      "iv": 0.24, "delta": 0.10, "gamma": 0.02,
                      "theta": -0.02, "vega": 0.05,
                      "volume": 300, "oi": 1500, "dte": 30},
        },
        "2026-07-17": {
            "450.0": {"bid": 8.5,  "ask": 8.75, "mark": 8.625, "last": 8.60,
                      "iv": 0.21, "delta": 0.52, "gamma": 0.03,
                      "theta": -0.03, "vega": 0.18,
                      "volume": 600, "oi": 2500, "dte": 58},
        },
    },
    "puts": {
        "2026-06-19": {
            "440.0": {"bid": 1.0,  "ask": 1.2,  "mark": 1.1,  "last": 1.1,
                      "iv": 0.24, "delta": -0.25, "gamma": 0.04,
                      "theta": -0.04, "vega": 0.10,
                      "volume": 700, "oi": 3000, "dte": 30},
            "450.0": {"bid": 4.8,  "ask": 5.0,  "mark": 4.9,  "last": 4.95,
                      "iv": 0.21, "delta": -0.50, "gamma": 0.05,
                      "theta": -0.04, "vega": 0.12,
                      "volume": 1200, "oi": 6000, "dte": 30},
        },
    },
    "expirations": ["2026-06-19", "2026-07-17"],
}


def _build_layer_with_mocks(
    *,
    candles: list[dict] | None = None,
    chain: dict | None = None,
) -> tuple[SchwabDataLayer, MagicMock]:
    """Build a SchwabDataLayer with a MagicMock SchwabClient.

    Both endpoints return the same data for every ticker call by default.
    Tests that need per-ticker variation set side_effect on mock_client
    manually after construction.
    """
    mock_client = MagicMock()
    mock_client.get_price_history.return_value = candles if candles is not None else _make_candles()
    mock_client.get_options_chain.return_value = chain if chain is not None else _SAMPLE_CHAIN_RESPONSE
    layer = SchwabDataLayer(mock_client)
    return layer, mock_client


# ── TestSnapshotShape ─────────────────────────────────────────────────────────

class TestSnapshotShape:

    def test_returns_market_state_instance(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        assert isinstance(result, MarketState)

    def test_contains_all_6_universe_tickers(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        assert set(result.tickers.keys()) == set(TICKER_UNIVERSE.keys())

    def test_correlations_present(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        # 6 choose 2 = 15 unique pairs.
        assert len(result.correlations) == 15


# ── TestTickerMapping ─────────────────────────────────────────────────────────

class TestTickerMapping:

    def test_last_price_from_daily_last_close(self):
        candles = _make_candles(n_days=60, start_close=440.0)
        expected_close = candles[-1]["close"]
        layer, _ = _build_layer_with_mocks(candles=candles)
        result = layer.snapshot()
        assert result.tickers["SPY"].last_price == round(expected_close, 2)

    def test_ohlcv_daily_passed_through(self):
        candles = _make_candles(n_days=45)
        layer, _ = _build_layer_with_mocks(candles=candles)
        result = layer.snapshot()
        assert len(result.tickers["SPY"].ohlcv_daily) == 45

    def test_ohlcv_hourly_is_empty_list(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        # D-η: hourly resample deferred to Sprint 6+.
        assert result.tickers["SPY"].ohlcv_hourly == []

    def test_iv_rank_default_50(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        assert result.tickers["SPY"].iv_rank == 50.0
        assert result.tickers["SPY"].iv_percentile == 50.0

    def test_realized_vol_computed_from_last_30_bars(self):
        # Constant return of 1% per day → daily logreturn ≈ 0.00995, σ_daily ≈ 0.
        # Use varying returns for a non-zero realized vol.
        candles = _make_candles(n_days=60, daily_return_pct=0.001)
        bars = [SchwabDataLayer._schwab_candle_to_ohlcv(c) for c in candles]
        expected = SchwabDataLayer._compute_realized_vol(bars[-30:])
        layer, _ = _build_layer_with_mocks(candles=candles)
        result = layer.snapshot()
        assert result.tickers["SPY"].realized_vol_30d == round(expected, 4)


# ── TestSkewFromChain ─────────────────────────────────────────────────────────

class TestSkewFromChain:

    def test_atm_iv_uses_call_at_closest_strike_to_spot(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        # Spot from _make_candles defaults ≈ 466.5 (440 * 1.001^60). Closest
        # available strike in the 30 DTE expiration is "470.0" (iv=0.24).
        # Verify atm_iv ∈ {known call IVs} at that expiration.
        atm_iv = result.tickers["SPY"].skew.atm_iv
        known_call_ivs = {0.18, 0.20, 0.22, 0.24}
        assert atm_iv in known_call_ivs

    def test_call_skew_iv_uses_25_delta_call(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        # Call with delta=0.25 → strike 460.0 → iv=0.22.
        assert result.tickers["SPY"].skew.call_skew_iv == 0.22

    def test_put_skew_iv_uses_minus_25_delta_put(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        # Put with delta=-0.25 → strike 440.0 → iv=0.24.
        assert result.tickers["SPY"].skew.put_skew_iv == 0.24

    def test_target_expiration_filter_picks_30dte_within_15days(self):
        # _SAMPLE_CHAIN_RESPONSE has DTE=30 (in range 30±15) and DTE=58 (out).
        # _find_target_expiration must pick "2026-06-19" (closest to 30, diff=0).
        chain = _SAMPLE_CHAIN_RESPONSE
        result = SchwabDataLayer._find_target_expiration(chain)
        assert result == "2026-06-19"

    def test_no_expiration_in_range_returns_zeros(self):
        # Chain with only DTE=200 (way outside ±15 window).
        far_chain = {
            "underlying": "SPY",
            "spot": {"last": 450.0, "bid": 449.0, "ask": 451.0,
                     "mark": 450.0, "volatility": 0.18},
            "calls": {
                "2026-12-19": {
                    "450.0": {"bid": 1.0, "ask": 1.1, "mark": 1.05, "last": 1.05,
                              "iv": 0.30, "delta": 0.50, "gamma": 0.01,
                              "theta": -0.01, "vega": 0.05,
                              "volume": 100, "oi": 500, "dte": 200},
                },
            },
            "puts": {},
            "expirations": ["2026-12-19"],
        }
        layer = SchwabDataLayer(MagicMock())
        skew = layer._build_skew_from_chain(far_chain, spot_price=450.0)
        assert skew.atm_iv == 0.0
        assert skew.put_skew_iv == 0.0
        assert skew.call_skew_iv == 0.0


# ── TestCorrelations ──────────────────────────────────────────────────────────

class TestCorrelations:

    def test_correlations_have_15_pairs(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        assert len(result.correlations) == 15

    def test_correlation_keys_alphabetically_sorted(self):
        layer, _ = _build_layer_with_mocks()
        result = layer.snapshot()
        for a, b in result.correlations.keys():
            assert a < b, f"Pair ({a}, {b}) not sorted alphabetically"

    def test_mismatched_length_returns_zero(self):
        # Direct call: when series lengths differ, correlation falls back to 0.0.
        base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars_long = [
            OHLCV(timestamp=base_ts + timedelta(days=i),
                  open=100.0, high=101.0, low=99.0, close=100.0 + i * 0.1,
                  volume=1_000_000)
            for i in range(60)
        ]
        bars_short = bars_long[:10]
        result = SchwabDataLayer._compute_correlations({
            "A": bars_long,
            "B": bars_short,
        })
        assert result[("A", "B")] == 0.0

    def test_correlation_computes_real_pearson_from_distinct_returns(self):
        # Build 2 OHLCV series where B's log returns are -A's → expected ρ = -1.0.
        base_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        returns_a = [0.01, -0.01, 0.02, -0.02, 0.015, -0.015, 0.01, -0.01]
        returns_b = [-r for r in returns_a]

        def _build_bars(returns: list[float], start: float = 100.0) -> list[OHLCV]:
            bars = [OHLCV(timestamp=base_ts, open=start, high=start, low=start,
                          close=start, volume=1_000_000)]
            for i, r in enumerate(returns):
                prev = bars[-1].close
                close = prev * exp(r)
                bars.append(OHLCV(
                    timestamp=base_ts + timedelta(days=i + 1),
                    open=prev, high=max(prev, close), low=min(prev, close),
                    close=close, volume=1_000_000,
                ))
            return bars

        bars_a = _build_bars(returns_a)
        bars_b = _build_bars(returns_b)
        result = SchwabDataLayer._compute_correlations({
            "A": bars_a, "B": bars_b,
        })
        assert result[("A", "B")] == pytest.approx(-1.0, abs=0.01)


# ── TestSchwabIntegration ─────────────────────────────────────────────────────

class TestSchwabIntegration:

    def test_calls_get_price_history_once_per_ticker(self):
        layer, mock_client = _build_layer_with_mocks()
        layer.snapshot()
        assert mock_client.get_price_history.call_count == len(TICKER_UNIVERSE)

    def test_calls_get_options_chain_once_per_ticker(self):
        layer, mock_client = _build_layer_with_mocks()
        layer.snapshot()
        assert mock_client.get_options_chain.call_count == len(TICKER_UNIVERSE)

    def test_schwab_api_error_propagates(self):
        layer, mock_client = _build_layer_with_mocks()
        mock_client.get_price_history.side_effect = SchwabAPIError("Schwab 500")
        with pytest.raises(SchwabAPIError, match="Schwab 500"):
            layer.snapshot()


# ── TestSchwabCandleConversion ────────────────────────────────────────────────

class TestSchwabCandleConversion:

    def test_epoch_ms_converted_to_utc_datetime(self):
        # 1714867200000 ms = 2024-05-05 00:00:00 UTC
        candle = {
            "datetime": 1714867200000,
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
            "volume": 1_000_000,
        }
        result = SchwabDataLayer._schwab_candle_to_ohlcv(candle)
        assert result.timestamp == datetime(2024, 5, 5, 0, 0, 0, tzinfo=timezone.utc)
        assert result.timestamp.tzinfo == timezone.utc

    def test_candle_fields_pass_through(self):
        candle = {
            "datetime": 1714867200000,
            "open": 100.5, "high": 102.1, "low": 99.8, "close": 101.7,
            "volume": 1_234_567,
        }
        result = SchwabDataLayer._schwab_candle_to_ohlcv(candle)
        assert result.open == 100.5
        assert result.high == 102.1
        assert result.low == 99.8
        assert result.close == 101.7
        assert result.volume == 1_234_567
