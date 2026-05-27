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


# ── TestLiveSnapshotBuilder (Sprint 11 atlas-d, ADR-013 D6) ───────────────────


from unittest.mock import MagicMock  # noqa: E402

from multi_agent.risk.portfolio_snapshot import LiveSnapshotBuilder  # noqa: E402


class TestLiveSnapshotBuilder:
    """LiveSnapshotBuilder builds PortfolioSnapshot from live Schwab reads.

    Covers ADR-013 D6 + sub-decisions D-η a D-λ + D-ι-A simplification.
    """

    @staticmethod
    def _mock_schwab_client(
        positions: list[dict] | None = None,
        balances: dict | None = None,
    ) -> MagicMock:
        """Helper: build SchwabClient mock con configurable returns."""
        client = MagicMock()
        client.get_positions.return_value = positions or []
        client.get_balances.return_value = balances or {
            "cash": 0.0,
            "buying_power": 0.0,
            "total_value": 0.0,
            "margin_used": 0.0,
            "day_trading_buying_power": 0.0,
        }
        return client

    def test_build_returns_portfolio_snapshot(self):
        """LiveSnapshotBuilder.build() returns PortfolioSnapshot instance."""
        client = self._mock_schwab_client()
        builder = LiveSnapshotBuilder(client)
        snapshot = builder.build()
        assert isinstance(snapshot, PortfolioSnapshot)

    def test_positions_mapped_to_position_views(self):
        """Schwab positions → tuple[PositionView, ...]."""
        positions = [
            {
                "symbol": "SPY",
                "asset_class": "EQUITY",
                "quantity": 100.0,
                "market_value": 45000.0,
                "average_price": 450.0,
                "unrealized_pnl": 0.0,
            }
        ]
        client = self._mock_schwab_client(positions=positions)
        builder = LiveSnapshotBuilder(client)
        snapshot = builder.build()
        assert len(snapshot.positions) == 1
        pv = snapshot.positions[0]
        assert pv.ticker == "SPY"
        assert pv.asset_class == "EQUITY"
        assert pv.quantity == 100  # float → int
        assert pv.market_value_usd == Decimal("45000.0")

    def test_greeks_default_zero(self):
        """D-η: delta/vega/theta default Decimal(0) (Schwab no greeks)."""
        positions = [{
            "symbol": "QQQ", "asset_class": "EQUITY", "quantity": 50.0,
            "market_value": 20000.0, "average_price": 400.0, "unrealized_pnl": 0.0,
        }]
        client = self._mock_schwab_client(positions=positions)
        snapshot = LiveSnapshotBuilder(client).build()
        pv = snapshot.positions[0]
        assert pv.delta == Decimal(0)
        assert pv.vega == Decimal(0)
        assert pv.theta == Decimal(0)

    def test_ticker_raw_no_occ_parser(self):
        """D-ι-A: symbol raw used as ticker (no OCC parser Phase 1)."""
        positions = [
            {"symbol": "SPY", "asset_class": "EQUITY", "quantity": 100.0,
             "market_value": 45000.0, "average_price": 450.0, "unrealized_pnl": 0.0},
            {"symbol": "SPY_062626P450", "asset_class": "OPTION",
             "quantity": -5.0, "market_value": -1250.0, "average_price": 2.5,
             "unrealized_pnl": 50.0, "option_type": "PUT", "strike": 450.0,
             "expiration": "2026-06-26"},
        ]
        client = self._mock_schwab_client(positions=positions)
        snapshot = LiveSnapshotBuilder(client).build()
        assert snapshot.positions[0].ticker == "SPY"  # equity
        assert snapshot.positions[1].ticker == "SPY_062626P450"  # OPTION raw

    def test_balances_aggregated_to_snapshot(self):
        """nav_usd ← total_value, cash_usd ← cash."""
        balances = {
            "cash": 50000.0,
            "buying_power": 100000.0,
            "total_value": 150000.0,
            "margin_used": 25000.0,
            "day_trading_buying_power": 200000.0,
        }
        client = self._mock_schwab_client(balances=balances)
        snapshot = LiveSnapshotBuilder(client).build()
        assert snapshot.nav_usd == Decimal("150000.0")
        assert snapshot.cash_usd == Decimal("50000.0")

    def test_buying_power_used_pct_computed(self):
        """buying_power_used_pct = (1 - bp/total) * 100."""
        balances = {
            "cash": 50000.0, "buying_power": 75000.0, "total_value": 150000.0,
            "margin_used": 0.0, "day_trading_buying_power": 0.0,
        }
        client = self._mock_schwab_client(balances=balances)
        snapshot = LiveSnapshotBuilder(client).build()
        # (1 - 75000/150000) * 100 = 50.0
        assert snapshot.buying_power_used_pct == 50.0

    def test_buying_power_pct_zero_when_no_nav(self):
        """Edge case: total_value=0 → buying_power_used_pct=0 (no div-by-zero)."""
        client = self._mock_schwab_client()  # all zeros default
        snapshot = LiveSnapshotBuilder(client).build()
        assert snapshot.buying_power_used_pct == 0.0

    def test_pnl_daily_summed_from_positions(self):
        """D-λ: pnl_daily_usd = sum positions[].unrealized_pnl."""
        positions = [
            {"symbol": "SPY", "asset_class": "EQUITY", "quantity": 100.0,
             "market_value": 45000.0, "average_price": 450.0, "unrealized_pnl": 500.0},
            {"symbol": "QQQ", "asset_class": "EQUITY", "quantity": 50.0,
             "market_value": 20000.0, "average_price": 400.0, "unrealized_pnl": -100.0},
        ]
        client = self._mock_schwab_client(positions=positions)
        snapshot = LiveSnapshotBuilder(client).build()
        assert snapshot.pnl_daily_usd == Decimal("400.0")  # 500 + (-100)

    def test_empty_positions_zero_pnl(self):
        """No positions → pnl_daily_usd = Decimal(0)."""
        client = self._mock_schwab_client(positions=[])
        snapshot = LiveSnapshotBuilder(client).build()
        assert snapshot.pnl_daily_usd == Decimal("0")

    def test_phase_1_defaults_zero(self):
        """D-θ + D-κ: portfolio_beta + pnl_weekly/monthly + drawdown = 0.0."""
        client = self._mock_schwab_client()
        snapshot = LiveSnapshotBuilder(client).build()
        assert snapshot.portfolio_beta == 0.0
        assert snapshot.pnl_daily_pct == 0.0
        assert snapshot.pnl_weekly_pct == 0.0
        assert snapshot.pnl_monthly_pct == 0.0
        assert snapshot.drawdown_from_peak_pct == 0.0

    def test_snapshot_at_utc(self):
        """snapshot_at populated UTC datetime + snapshot_id non-empty sha256."""
        client = self._mock_schwab_client()
        snapshot = LiveSnapshotBuilder(client).build()
        assert snapshot.snapshot_at.tzinfo is not None
        assert snapshot.snapshot_id  # non-empty
        assert len(snapshot.snapshot_id) == 64  # sha256 hex


# ── TestSupportsBuildProtocol (Sprint 12 protocol-a, ADR-013 §9.3 #5 resolved) ──

from multi_agent.risk.portfolio_snapshot import (  # noqa: E402
    CachedSnapshotBuilder,
    SnapshotBuilder,
    SupportsBuild,
)


class TestSupportsBuildProtocol:
    """SupportsBuild Protocol structural compliance verification.

    ADR-013 §9.3 #5 (F-r14) resolved Sprint 12 S.12.protocol-a:
    @runtime_checkable Protocol replacing duck-typed CachedSnapshotBuilder
    type hint. Both SnapshotBuilder + LiveSnapshotBuilder satisfy Protocol.
    """

    def test_snapshot_builder_satisfies_protocol(self):
        """SnapshotBuilder implements SupportsBuild (isinstance check)."""
        pool_mock = MagicMock()
        builder = SnapshotBuilder(pool_mock)
        assert isinstance(builder, SupportsBuild)

    def test_live_snapshot_builder_satisfies_protocol(self):
        """LiveSnapshotBuilder implements SupportsBuild (isinstance check)."""
        schwab_mock = MagicMock()
        builder = LiveSnapshotBuilder(schwab_mock)
        assert isinstance(builder, SupportsBuild)

    def test_non_builder_rejected_by_protocol(self):
        """Random class without build() method fails Protocol check."""
        class NotABuilder:
            pass

        instance = NotABuilder()
        assert not isinstance(instance, SupportsBuild)
        assert not isinstance(object(), SupportsBuild)

    def test_cached_snapshot_builder_accepts_protocol_compliant(self):
        """CachedSnapshotBuilder.__init__ accepts any SupportsBuild instance.

        Verifies Protocol-based type hint works pragmatically: a Mock
        configured con build() method returning PortfolioSnapshot is accepted
        by CachedSnapshotBuilder.
        """
        snapshot_stub = MagicMock()
        snapshot_stub.snapshot_id = "a" * 64
        mock_builder = MagicMock()
        mock_builder.build.return_value = snapshot_stub

        cached = CachedSnapshotBuilder(mock_builder, ttl_seconds=10.0)

        result = cached.get()
        mock_builder.build.assert_called_once()
        assert result is snapshot_stub
