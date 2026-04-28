"""Tests for PortfolioSnapshot model and snapshot_hash."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from multi_agent.risk.portfolio_snapshot import (
    PortfolioSnapshot,
    PositionView,
    snapshot_hash,
)


def _pos(ticker: str, qty: int, price: float, vega: float = 0.0) -> PositionView:
    return PositionView(
        ticker=ticker,
        asset_class="equity",
        strategy_type=None,
        market_value_usd=Decimal(str(abs(qty) * price)),
        quantity=qty,
        delta=Decimal(str(abs(qty))),
        vega=Decimal(str(vega)),
        theta=Decimal("0"),
    )


def _snap(positions=None, nav=1_000_000.0, cash=850_000.0, pnl_daily=0.0,
          drawdown=-2.1, beta=0.82, vega_total=-12400.0, bp_pct=16.0) -> PortfolioSnapshot:
    pos = positions or [_pos("MSFT", 100, 440.0), _pos("NVDA", 50, 850.0)]
    ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
    sid = snapshot_hash(pos, Decimal(str(cash)), Decimal(str(pnl_daily)), ts)
    return PortfolioSnapshot(
        positions=tuple(pos),
        nav_usd=Decimal(str(nav)),
        cash_usd=Decimal(str(cash)),
        buying_power_used_pct=bp_pct,
        portfolio_beta=beta,
        vega_total=vega_total,
        pnl_daily_usd=Decimal(str(pnl_daily)),
        pnl_daily_pct=pnl_daily / nav * 100,
        pnl_weekly_pct=0.0,
        pnl_monthly_pct=0.0,
        drawdown_from_peak_pct=drawdown,
        snapshot_at=ts,
        snapshot_id=sid,
    )


class TestSnapshotHash:
    def test_same_inputs_same_hash(self):
        pos = [_pos("MSFT", 100, 440.0), _pos("NVDA", 50, 850.0)]
        ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
        h1 = snapshot_hash(pos, Decimal("850000"), Decimal("100.00"), ts)
        h2 = snapshot_hash(pos, Decimal("850000"), Decimal("100.00"), ts)
        assert h1 == h2

    def test_different_positions_different_hash(self):
        pos_a = [_pos("MSFT", 100, 440.0)]
        pos_b = [_pos("AAPL", 100, 220.0)]
        ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
        h1 = snapshot_hash(pos_a, Decimal("850000"), Decimal("0"), ts)
        h2 = snapshot_hash(pos_b, Decimal("850000"), Decimal("0"), ts)
        assert h1 != h2

    def test_order_independent(self):
        pos_ab = [_pos("MSFT", 100, 440.0), _pos("AAPL", 80, 220.0)]
        pos_ba = [_pos("AAPL", 80, 220.0), _pos("MSFT", 100, 440.0)]
        ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
        h1 = snapshot_hash(pos_ab, Decimal("850000"), Decimal("0"), ts)
        h2 = snapshot_hash(pos_ba, Decimal("850000"), Decimal("0"), ts)
        assert h1 == h2

    def test_different_minute_different_hash(self):
        pos = [_pos("MSFT", 100, 440.0)]
        ts_a = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
        ts_b = datetime(2026, 4, 28, 14, 31, 0, tzinfo=timezone.utc)
        h1 = snapshot_hash(pos, Decimal("850000"), Decimal("0"), ts_a)
        h2 = snapshot_hash(pos, Decimal("850000"), Decimal("0"), ts_b)
        assert h1 != h2

    def test_same_minute_same_hash(self):
        pos = [_pos("MSFT", 100, 440.0)]
        ts_a = datetime(2026, 4, 28, 14, 30, 15, tzinfo=timezone.utc)
        ts_b = datetime(2026, 4, 28, 14, 30, 55, tzinfo=timezone.utc)
        h1 = snapshot_hash(pos, Decimal("850000"), Decimal("0"), ts_a)
        h2 = snapshot_hash(pos, Decimal("850000"), Decimal("0"), ts_b)
        assert h1 == h2

    def test_pnl_rounded_to_2_decimals(self):
        """Small floating point noise in pnl should not change hash."""
        pos = [_pos("MSFT", 100, 440.0)]
        ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
        h1 = snapshot_hash(pos, Decimal("850000"), Decimal("100.001"), ts)
        h2 = snapshot_hash(pos, Decimal("850000"), Decimal("100.009"), ts)
        assert h1 == h2  # both round to 100.00

    def test_hash_is_64_char_hex(self):
        pos = [_pos("MSFT", 100, 440.0)]
        ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
        h = snapshot_hash(pos, Decimal("850000"), Decimal("0"), ts)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestExposureHelpers:
    def test_exposure_pct_known_position(self):
        snap = _snap(positions=[_pos("MSFT", 100, 440.0)])
        assert snap.exposure_pct("MSFT") == pytest.approx(4.4, abs=0.01)

    def test_exposure_pct_unknown_ticker_zero(self):
        snap = _snap()
        assert snap.exposure_pct("ZZZZ") == 0.0

    def test_exposure_pct_case_insensitive(self):
        snap = _snap(positions=[_pos("MSFT", 100, 440.0)])
        assert snap.exposure_pct("msft") == snap.exposure_pct("MSFT")

    def test_sector_exposure_pct_sums_tickers(self):
        snap = _snap(positions=[
            _pos("MSFT", 100, 440.0),
            _pos("AAPL", 80, 220.0),
        ])
        tickers = frozenset({"MSFT", "AAPL"})
        expected = (100 * 440 + 80 * 220) / 1_000_000 * 100
        assert snap.sector_exposure_pct(tickers) == pytest.approx(expected, abs=0.01)

    def test_sector_exposure_pct_empty_frozenset_zero(self):
        snap = _snap()
        assert snap.sector_exposure_pct(frozenset()) == 0.0
