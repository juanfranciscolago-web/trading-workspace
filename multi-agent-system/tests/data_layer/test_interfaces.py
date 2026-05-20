"""Unit tests for TickerSnapshot + MarketState Phase 2 extensions (S.10.cons-c).

Covers ADR-009 D2 sub-decisions D2-1/D2-2/D2-3 + D7 backward compatibility.
F-r2/F-r3/F-r4 catches verified.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from multi_agent.data_layer.interfaces import (
    MarketState,
    OHLCV,
    SkewSnapshot,
    TickerSnapshot,
)

_TS = datetime(2026, 5, 19, 21, 30, tzinfo=timezone.utc)


def _make_ohlcv(ts: datetime = _TS) -> OHLCV:
    return OHLCV(timestamp=ts, open=450.0, high=452.0, low=449.0, close=451.0, volume=1_000_000)


def _make_skew() -> SkewSnapshot:
    return SkewSnapshot(atm_iv=0.20, put_skew_iv=0.22, call_skew_iv=0.19)


def _make_ticker_minimal() -> TickerSnapshot:
    """TickerSnapshot construction backward-compat (8 fields only, NEW fields default)."""
    return TickerSnapshot(
        ticker="SPY",
        last_price=451.0,
        ohlcv_daily=[_make_ohlcv()],
        ohlcv_hourly=[],
        iv_rank=50.0,
        iv_percentile=45.0,
        skew=_make_skew(),
        realized_vol_30d=0.18,
    )


class TestTickerSnapshotPhase2Fields:
    """3 NEW fields per ADR-009 D2-1/D2-2/D2-3 + backward compat (D7)."""

    def test_default_term_structure_empty(self):
        """D2-1 + D7: term_structure defaults [] (backward compat)."""
        ts = _make_ticker_minimal()
        assert ts.term_structure == []

    def test_default_surface_empty(self):
        """D2-2 + D7: surface defaults {} (backward compat)."""
        ts = _make_ticker_minimal()
        assert ts.surface == {}

    def test_default_ohlcv_intraday_empty(self):
        """D2-3 + D7: ohlcv_intraday defaults {} (backward compat)."""
        ts = _make_ticker_minimal()
        assert ts.ohlcv_intraday == {}

    def test_term_structure_ordering_preserved(self):
        """D2-1: list[tuple[int, float]] ordering preserved front-to-back."""
        ts = TickerSnapshot(
            ticker="SPY", last_price=451.0, ohlcv_daily=[], ohlcv_hourly=[],
            iv_rank=50.0, iv_percentile=45.0, skew=_make_skew(), realized_vol_30d=0.18,
            term_structure=[(7, 0.18), (14, 0.19), (30, 0.21), (60, 0.22)],
        )
        assert ts.term_structure[0] == (7, 0.18)
        assert ts.term_structure[3] == (60, 0.22)
        assert all(isinstance(t, tuple) and len(t) == 2 for t in ts.term_structure)

    def test_surface_dte_keyed_with_skew_values(self):
        """D2-2 canonical: keys=DTE, values=[atm_iv, put_25d_iv, call_25d_iv]."""
        ts = TickerSnapshot(
            ticker="SPY", last_price=451.0, ohlcv_daily=[], ohlcv_hourly=[],
            iv_rank=50.0, iv_percentile=45.0, skew=_make_skew(), realized_vol_30d=0.18,
            surface={7: [0.20, 0.18, 0.22], 35: [0.22, 0.20, 0.24]},
        )
        assert ts.surface[7] == [0.20, 0.18, 0.22]
        assert ts.surface[35] == [0.22, 0.20, 0.24]
        assert all(len(v) == 3 for v in ts.surface.values())  # [atm, put25d, call25d]

    def test_ohlcv_intraday_timeframe_keys(self):
        """D2-3: dict[str, list[OHLCV]] keyed by timeframe."""
        bar_5m = _make_ohlcv()
        bar_15m = _make_ohlcv()
        ts = TickerSnapshot(
            ticker="SPY", last_price=451.0, ohlcv_daily=[], ohlcv_hourly=[],
            iv_rank=50.0, iv_percentile=45.0, skew=_make_skew(), realized_vol_30d=0.18,
            ohlcv_intraday={"5m": [bar_5m, bar_5m], "15m": [bar_15m]},
        )
        assert "5m" in ts.ohlcv_intraday
        assert "15m" in ts.ohlcv_intraday
        assert len(ts.ohlcv_intraday["5m"]) == 2
        assert len(ts.ohlcv_intraday["15m"]) == 1

    def test_frozen_immutability_term_structure(self):
        """frozen=True: TickerSnapshot cannot reassign term_structure."""
        ts = _make_ticker_minimal()
        with pytest.raises(Exception):  # FrozenInstanceError o AttributeError
            ts.term_structure = [(7, 0.18)]

    def test_frozen_immutability_surface(self):
        """frozen=True: cannot reassign surface."""
        ts = _make_ticker_minimal()
        with pytest.raises(Exception):
            ts.surface = {25: [0.20]}

    def test_frozen_immutability_ohlcv_intraday(self):
        """frozen=True: cannot reassign ohlcv_intraday."""
        ts = _make_ticker_minimal()
        with pytest.raises(Exception):
            ts.ohlcv_intraday = {"5m": []}


class TestMarketStateToDictExtension:
    """to_dict() serializer Phase 2 extensions (F-r2/F-r3/F-r4 catches)."""

    def test_empty_new_fields_serialize(self):
        """Defaults serialize OK: [], {}, {}."""
        ts = _make_ticker_minimal()
        state = MarketState(timestamp=_TS, tickers={"SPY": ts}, correlations={})
        d = state.to_dict()
        spy = d["tickers"]["SPY"]
        assert spy["term_structure"] == []
        assert spy["surface"] == {}
        assert spy["ohlcv_intraday"] == {}

    def test_term_structure_tuples_to_lists(self):
        """F-r2: asdict() preserves tuples, to_dict() converts to lists JSON-compat."""
        ts = TickerSnapshot(
            ticker="SPY", last_price=451.0, ohlcv_daily=[], ohlcv_hourly=[],
            iv_rank=50.0, iv_percentile=45.0, skew=_make_skew(), realized_vol_30d=0.18,
            term_structure=[(7, 0.18), (14, 0.19)],
        )
        state = MarketState(timestamp=_TS, tickers={"SPY": ts}, correlations={})
        d = state.to_dict()
        result = d["tickers"]["SPY"]["term_structure"]
        assert result == [[7, 0.18], [14, 0.19]]
        assert all(isinstance(t, list) for t in result)

    def test_surface_int_keys_to_str(self):
        """F-r4: JSON requires string object keys. surface DTE int keys → str."""
        ts = TickerSnapshot(
            ticker="SPY", last_price=451.0, ohlcv_daily=[], ohlcv_hourly=[],
            iv_rank=50.0, iv_percentile=45.0, skew=_make_skew(), realized_vol_30d=0.18,
            surface={7: [0.20, 0.18, 0.22], 35: [0.22, 0.20, 0.24]},
        )
        state = MarketState(timestamp=_TS, tickers={"SPY": ts}, correlations={})
        d = state.to_dict()
        result = d["tickers"]["SPY"]["surface"]
        assert result == {"7": [0.20, 0.18, 0.22], "35": [0.22, 0.20, 0.24]}
        assert all(isinstance(k, str) for k in result.keys())

    def test_ohlcv_intraday_timestamps_isoformat(self):
        """F-r3: nested OHLCV timestamps converted to isoformat strings."""
        bar = _make_ohlcv()
        ts = TickerSnapshot(
            ticker="SPY", last_price=451.0, ohlcv_daily=[], ohlcv_hourly=[],
            iv_rank=50.0, iv_percentile=45.0, skew=_make_skew(), realized_vol_30d=0.18,
            ohlcv_intraday={"5m": [bar, bar], "15m": [bar]},
        )
        state = MarketState(timestamp=_TS, tickers={"SPY": ts}, correlations={})
        d = state.to_dict()
        result = d["tickers"]["SPY"]["ohlcv_intraday"]
        # All timestamps converted to isoformat strings
        for timeframe_bars in result.values():
            for bar_d in timeframe_bars:
                assert isinstance(bar_d["timestamp"], str)
                assert bar_d["timestamp"] == _TS.isoformat()


class TestBackwardCompatibility:
    """D7: existing TickerSnapshot constructors NOT touched by Sprint 10."""

    def test_existing_8_fields_construction(self):
        """Pre-Sprint 10 constructor sin new fields works."""
        ts = _make_ticker_minimal()
        assert ts.ticker == "SPY"
        assert ts.last_price == 451.0
        assert ts.iv_rank == 50.0
        assert ts.realized_vol_30d == 0.18

    def test_existing_market_state_to_dict(self):
        """Pre-Sprint 10 MarketState serialization preserved (timestamp + ohlcv_daily isoformat)."""
        ts = _make_ticker_minimal()
        state = MarketState(timestamp=_TS, tickers={"SPY": ts}, correlations={})
        d = state.to_dict()
        # Timestamp + ohlcv_daily timestamps still isoformat (pre-existing pattern)
        assert d["timestamp"] == _TS.isoformat()
        assert d["tickers"]["SPY"]["ohlcv_daily"][0]["timestamp"] == _TS.isoformat()
