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

import logging
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


# ── TestIvRankProgressive ─────────────────────────────────────────────────────

class TestIvRankProgressive:
    """SchwabDataLayer iv_rank progressive disclosure (ADR-005 D5, S.6.iv-d).

    5 paths tested per D5 thresholds + the no-repo backward-compat baseline:
      - iv_history_repo=None  → 50.0 fallback  (DEBUG, distinct message)
      - N < 10                → 50.0 fallback  (DEBUG, bootstrap)
      - 10 <= N < 30          → percentile     (WARNING)
      - 30 <= N < 252         → percentile     (INFO)
      - N >= 252              → percentile     (DEBUG, silent)

    Tests call _compute_iv_rank_progressive directly (focused unit-level)
    rather than going through snapshot(), to keep assertions tight and
    avoid the rest of the chain/candles infra.
    """

    _LOGGER_NAME = "multi_agent.data_layer.schwab_data_layer"

    def test_fallback_50_when_no_iv_history_repo(self):
        """Default path: no iv_history_repo wired → 50.0 fallback per D5."""
        layer = SchwabDataLayer(schwab_client=MagicMock())
        result = layer._compute_iv_rank_progressive("SPY", current_iv=0.20)
        assert result == 50.0

    def test_fallback_50_when_history_below_10(self):
        """N=5 (< 10) → 50.0 bootstrap fallback. Repo IS called once."""
        mock_repo = MagicMock()
        mock_repo.get_history.return_value = [0.15, 0.16, 0.18, 0.19, 0.20]  # N=5

        layer = SchwabDataLayer(
            schwab_client=MagicMock(),
            iv_history_repo=mock_repo,
        )
        result = layer._compute_iv_rank_progressive("SPY", current_iv=0.20)

        assert result == 50.0
        mock_repo.get_history.assert_called_once_with("SPY", days=252)

    def test_computes_with_warning_when_history_10_to_30(self, caplog):
        """N=20 (10 ≤ N < 30) → percentile + WARNING log."""
        history = [0.10 + i * 0.01 for i in range(20)]  # [0.10..0.29]
        mock_repo = MagicMock()
        mock_repo.get_history.return_value = history

        layer = SchwabDataLayer(
            schwab_client=MagicMock(),
            iv_history_repo=mock_repo,
        )

        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = layer._compute_iv_rank_progressive("SPY", current_iv=0.195)

        # current_iv 0.195 sits at midpoint of [0.10, 0.29] → rank ≈ 50.
        assert result == pytest.approx(50.0, abs=1.0)

        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and r.name == self._LOGGER_NAME
        ]
        assert any("iv_rank computed on N=20 days" in r.message for r in warnings)

    def test_computes_with_info_when_history_30_to_252(self, caplog):
        """N=100 (30 ≤ N < 252) → percentile + INFO log (no WARNING)."""
        history = [0.10 + i * (0.20 / 99) for i in range(100)]  # [0.10..0.30]
        mock_repo = MagicMock()
        mock_repo.get_history.return_value = history

        layer = SchwabDataLayer(
            schwab_client=MagicMock(),
            iv_history_repo=mock_repo,
        )

        with caplog.at_level(logging.INFO, logger=self._LOGGER_NAME):
            result = layer._compute_iv_rank_progressive("SPY", current_iv=0.20)

        # current_iv 0.20 midpoint of [0.10, 0.30] → rank ≈ 50.
        assert result == pytest.approx(50.0, abs=1.0)

        infos = [
            r for r in caplog.records
            if r.levelno == logging.INFO and r.name == self._LOGGER_NAME
        ]
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and r.name == self._LOGGER_NAME
        ]
        assert any("iv_rank computed on N=100 days" in r.message for r in infos)
        assert len(warnings) == 0

    def test_computes_silently_when_history_above_252(self, caplog):
        """N=300 (≥ 252) → percentile + DEBUG log (no INFO / WARNING)."""
        history = [0.10 + i * (0.20 / 299) for i in range(300)]  # [0.10..0.30]
        mock_repo = MagicMock()
        mock_repo.get_history.return_value = history

        layer = SchwabDataLayer(
            schwab_client=MagicMock(),
            iv_history_repo=mock_repo,
        )

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER_NAME):
            result = layer._compute_iv_rank_progressive("SPY", current_iv=0.20)

        assert result == pytest.approx(50.0, abs=1.0)

        debugs = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG and r.name == self._LOGGER_NAME
        ]
        infos = [
            r for r in caplog.records
            if r.levelno == logging.INFO and r.name == self._LOGGER_NAME
        ]
        warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and r.name == self._LOGGER_NAME
        ]
        assert any("iv_rank computed on full N=300 days" in r.message for r in debugs)
        assert len(infos) == 0
        assert len(warnings) == 0


# ── TestPhase2ConsumerSurface (Sprint 10 S.10.cons-d, ADR-009 D4) ─────────────


class TestPhase2ConsumerSurface:
    """SchwabDataLayer Phase 2 fields per ADR-009 D4 + D4-1/D4-2/D4-3."""

    _LOGGER_NAME = "multi_agent.data_layer.schwab_data_layer"

    def _build_layer_with_repos(
        self,
        *,
        iv_surface_repo: MagicMock | None = None,
        ohlcv_repo: MagicMock | None = None,
    ) -> tuple[SchwabDataLayer, MagicMock]:
        mock_client = MagicMock()
        mock_client.get_price_history.return_value = _make_candles()
        mock_client.get_options_chain.return_value = _SAMPLE_CHAIN_RESPONSE
        layer = SchwabDataLayer(
            mock_client,
            iv_surface_repo=iv_surface_repo,
            ohlcv_repo=ohlcv_repo,
        )
        return layer, mock_client

    def test_build_phase2_empty_when_repos_none(self):
        """D4-3: si iv_surface_repo + ohlcv_repo None, return defaults vacíos."""
        layer, _ = self._build_layer_with_repos()
        result = layer._build_phase2_fields("SPY")
        assert result == {"term_structure": [], "surface": {}, "ohlcv_intraday": {}}

    def test_build_phase2_warns_when_iv_surface_empty(self, caplog):
        """D4-3: get_latest_surface None → log WARNING + skip surface fields."""
        iv_surface_repo = MagicMock()
        iv_surface_repo.get_latest_surface.return_value = None
        ohlcv_repo = MagicMock()
        ohlcv_repo.get_bars.return_value = []
        layer, _ = self._build_layer_with_repos(
            iv_surface_repo=iv_surface_repo, ohlcv_repo=ohlcv_repo,
        )

        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = layer._build_phase2_fields("SPY")

        assert result["term_structure"] == []
        assert result["surface"] == {}
        assert any("no iv_surface data for SPY" in r.message for r in caplog.records)

    def test_build_phase2_populates_term_structure(self):
        """D4 + S.10.cons-b: term_structure from IvSurfaceRepository.get_term_structure."""
        latest_ts = datetime(2026, 5, 19, 21, 15, tzinfo=timezone.utc)
        iv_surface_repo = MagicMock()
        iv_surface_repo.get_latest_surface.return_value = latest_ts
        iv_surface_repo.get_term_structure.return_value = [(7, 0.20), (35, 0.22)]
        iv_surface_repo.get_surface_for_ticker.return_value = []
        ohlcv_repo = MagicMock()
        ohlcv_repo.get_bars.return_value = []
        layer, _ = self._build_layer_with_repos(
            iv_surface_repo=iv_surface_repo, ohlcv_repo=ohlcv_repo,
        )

        result = layer._build_phase2_fields("SPY")

        assert result["term_structure"] == [(7, 0.20), (35, 0.22)]
        iv_surface_repo.get_term_structure.assert_called_once_with("SPY", latest_ts)

    def test_build_phase2_dte_keyed_surface_with_skew(self):
        """D2-2 canonical + D4-1: surface dict[DTE] = [atm, put25d, call25d]."""
        from datetime import date as _date
        latest_ts = datetime(2026, 5, 19, 21, 15, tzinfo=timezone.utc)
        iv_surface_repo = MagicMock()
        iv_surface_repo.get_latest_surface.return_value = latest_ts
        iv_surface_repo.get_term_structure.return_value = []
        # Provide rows con 3 expirations + delta buckets
        iv_surface_repo.get_surface_for_ticker.return_value = [
            # 7-DTE expiration
            {"expiration": _date(2026, 5, 26), "option_type": "CALL", "delta": 0.50, "iv": 0.20},
            {"expiration": _date(2026, 5, 26), "option_type": "PUT", "delta": -0.25, "iv": 0.18},
            {"expiration": _date(2026, 5, 26), "option_type": "CALL", "delta": 0.25, "iv": 0.22},
            # 35-DTE expiration
            {"expiration": _date(2026, 6, 23), "option_type": "CALL", "delta": 0.50, "iv": 0.22},
            {"expiration": _date(2026, 6, 23), "option_type": "PUT", "delta": -0.25, "iv": 0.20},
            {"expiration": _date(2026, 6, 23), "option_type": "CALL", "delta": 0.25, "iv": 0.24},
        ]
        ohlcv_repo = MagicMock()
        ohlcv_repo.get_bars.return_value = []
        layer, _ = self._build_layer_with_repos(
            iv_surface_repo=iv_surface_repo, ohlcv_repo=ohlcv_repo,
        )

        result = layer._build_phase2_fields("SPY")

        assert 7 in result["surface"]
        assert 35 in result["surface"]
        # Each value = [atm, put25d, call25d]
        assert result["surface"][7] == [0.20, 0.18, 0.22]
        assert result["surface"][35] == [0.22, 0.20, 0.24]

    def test_delta_bucketing_atm_50d_range(self):
        """D4-1: ATM bucket = |delta| ∈ [45, 55] averaged."""
        from datetime import date as _date
        ts = datetime(2026, 5, 19, 21, 15, tzinfo=timezone.utc)
        rows = [
            {"expiration": _date(2026, 5, 26), "option_type": "CALL", "delta": 0.48, "iv": 0.20},
            {"expiration": _date(2026, 5, 26), "option_type": "PUT", "delta": -0.52, "iv": 0.22},
        ]
        result = SchwabDataLayer._build_dte_skew_surface(rows, ts)
        # ATM = avg(0.20, 0.22) = 0.21
        assert result[7][0] == pytest.approx(0.21)

    def test_delta_bucketing_put_25d_range(self):
        """D4-1: put_25d bucket = PUT con |delta| ∈ [20, 30]."""
        from datetime import date as _date
        ts = datetime(2026, 5, 19, 21, 15, tzinfo=timezone.utc)
        rows = [
            {"expiration": _date(2026, 5, 26), "option_type": "CALL", "delta": 0.50, "iv": 0.20},
            {"expiration": _date(2026, 5, 26), "option_type": "PUT", "delta": -0.25, "iv": 0.18},
            {"expiration": _date(2026, 5, 26), "option_type": "PUT", "delta": -0.28, "iv": 0.19},
        ]
        result = SchwabDataLayer._build_dte_skew_surface(rows, ts)
        # put_25d = avg(0.18, 0.19) = 0.185
        assert result[7][1] == pytest.approx(0.185)

    def test_delta_bucketing_call_25d_range(self):
        """D4-1: call_25d bucket = CALL con delta ∈ [20, 30]."""
        from datetime import date as _date
        ts = datetime(2026, 5, 19, 21, 15, tzinfo=timezone.utc)
        rows = [
            {"expiration": _date(2026, 5, 26), "option_type": "CALL", "delta": 0.50, "iv": 0.20},
            {"expiration": _date(2026, 5, 26), "option_type": "CALL", "delta": 0.25, "iv": 0.22},
            {"expiration": _date(2026, 5, 26), "option_type": "CALL", "delta": 0.23, "iv": 0.23},
        ]
        result = SchwabDataLayer._build_dte_skew_surface(rows, ts)
        # call_25d = avg(0.22, 0.23) = 0.225
        assert result[7][2] == pytest.approx(0.225)

    def test_delta_bucketing_empty_fallback_to_atm(self):
        """D4-1: si put_25d or call_25d bucket empty, fallback to atm_iv."""
        from datetime import date as _date
        ts = datetime(2026, 5, 19, 21, 15, tzinfo=timezone.utc)
        # Only ATM strike, no 25d skew strikes
        rows = [
            {"expiration": _date(2026, 5, 26), "option_type": "CALL", "delta": 0.50, "iv": 0.20},
        ]
        result = SchwabDataLayer._build_dte_skew_surface(rows, ts)
        # Both put_25d + call_25d fallback to atm_iv = 0.20
        assert result[7] == [0.20, 0.20, 0.20]

    def test_ohlcv_intraday_populated_4_timeframes(self):
        """D4-2: TIMEFRAME_LOOKBACK_BARS produces 4 timeframe keys."""
        iv_surface_repo = MagicMock()
        iv_surface_repo.get_latest_surface.return_value = None
        ohlcv_repo = MagicMock()
        ts = datetime(2026, 5, 19, 21, 0, tzinfo=timezone.utc)
        ohlcv_repo.get_bars.return_value = [
            {"ts": ts, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000},
        ]
        layer, _ = self._build_layer_with_repos(
            iv_surface_repo=iv_surface_repo, ohlcv_repo=ohlcv_repo,
        )

        result = layer._build_phase2_fields("SPY")

        assert set(result["ohlcv_intraday"].keys()) == {"5m", "15m", "30m", "1d"}
        # Each timeframe has 1 bar (from mock return)
        for timeframe, bars in result["ohlcv_intraday"].items():
            assert len(bars) == 1
            assert isinstance(bars[0], OHLCV)

    def test_ohlcv_intraday_warns_on_repo_error(self, caplog):
        """D4-3: ohlcv_repo.get_bars raises → log WARNING + empty list per timeframe."""
        iv_surface_repo = MagicMock()
        iv_surface_repo.get_latest_surface.return_value = None
        ohlcv_repo = MagicMock()
        ohlcv_repo.get_bars.side_effect = RuntimeError("DB connection broken")
        layer, _ = self._build_layer_with_repos(
            iv_surface_repo=iv_surface_repo, ohlcv_repo=ohlcv_repo,
        )

        with caplog.at_level(logging.WARNING, logger=self._LOGGER_NAME):
            result = layer._build_phase2_fields("SPY")

        # All 4 timeframes have empty list (D-γ isolation)
        for timeframe in ("5m", "15m", "30m", "1d"):
            assert result["ohlcv_intraday"][timeframe] == []
        # Warning logged for each failed timeframe
        assert sum(
            1 for r in caplog.records
            if "ohlcv read failed for SPY" in r.message
        ) == 4
