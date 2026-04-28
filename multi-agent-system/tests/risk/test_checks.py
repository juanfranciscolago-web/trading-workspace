"""
Unit tests for ATLAS check functions.
~45 tests, one per boundary condition.
All pure — no DB, no Redis.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from multi_agent.communication.enums import AtlasReason
from multi_agent.risk.checks import (
    CheckResult,
    check_beta,
    check_bucket_saturation,
    check_buying_power,
    check_kill_switches,
    check_pnl_halt,
    check_sector_saturation,
    check_single_name,
    check_vega,
)
from multi_agent.risk.config import BucketConfig, BucketDef, Phase1Limits
from multi_agent.risk.portfolio_snapshot import PortfolioSnapshot, PositionView, snapshot_hash


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _pos(ticker, qty=100, price=440.0, vega=0.0) -> PositionView:
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


def _limits(
    daily_halt=-2.5,
    weekly_halt=-4.0,
    drawdown_halt=-12.0,
    drawdown_kill=-25.0,
    daily_kill=-8.0,
    single_name=8.0,
    sector=30.0,
    bucket=45.0,
    beta_min=-0.3,
    beta_max=1.3,
    vega_pct=3.0,
    bp_normal=40.0,
    bp_macro=25.0,
) -> Phase1Limits:
    from multi_agent.risk.config import (
        BuyingPowerLimits,
        ExposureLimits,
        GreekLimits,
        PnlLimits,
    )
    return Phase1Limits(
        phase=1,
        pnl=PnlLimits(
            daily_halt_pct=daily_halt,
            weekly_halt_pct=weekly_halt,
            monthly_size_reduction_pct=-7.0,
            drawdown_halt_pct=drawdown_halt,
            drawdown_kill_switch_pct=drawdown_kill,
            daily_loss_kill_switch_pct=daily_kill,
        ),
        exposure=ExposureLimits(
            single_name_max_pct=single_name,
            sector_max_pct=sector,
            bucket_max_pct=bucket,
            beta_min=beta_min,
            beta_max=beta_max,
        ),
        greeks=GreekLimits(vega_limit_pct_per_vix_point=vega_pct),
        buying_power=BuyingPowerLimits(normal_max_pct=bp_normal, macro_event_max_pct=bp_macro),
    )


def _snap(
    drawdown=-2.1,
    pnl_daily_pct=0.0,
    pnl_weekly_pct=0.0,
    positions=None,
    nav=1_000_000.0,
    bp_pct=16.0,
    beta=0.82,
    vega_total=-12400.0,
) -> PortfolioSnapshot:
    pos = positions or [_pos("MSFT", 100, 440.0), _pos("NVDA", 50, 850.0)]
    ts = datetime(2026, 4, 28, 14, 30, 0, tzinfo=timezone.utc)
    sid = snapshot_hash(pos, Decimal(str(nav * 0.85)), Decimal(str(pnl_daily_pct / 100 * nav)), ts)
    return PortfolioSnapshot(
        positions=tuple(pos),
        nav_usd=Decimal(str(nav)),
        cash_usd=Decimal(str(nav * 0.85)),
        buying_power_used_pct=bp_pct,
        portfolio_beta=beta,
        vega_total=vega_total,
        pnl_daily_usd=Decimal(str(pnl_daily_pct / 100 * nav)),
        pnl_daily_pct=pnl_daily_pct,
        pnl_weekly_pct=pnl_weekly_pct,
        pnl_monthly_pct=0.0,
        drawdown_from_peak_pct=drawdown,
        snapshot_at=ts,
        snapshot_id=sid,
    )


def _buckets() -> BucketConfig:
    return BucketConfig(buckets={
        "tech_mega_cap": BucketDef(description="Tech", tickers=("MSFT", "AAPL", "GOOGL")),
        "semis": BucketDef(description="Semis", tickers=("NVDA", "AMD")),
        "other": BucketDef(description="Other", tickers=()),
    })


# ── check_kill_switches ───────────────────────────────────────────────────────

class TestKillSwitches:
    def test_healthy_portfolio_passes(self):
        r = check_kill_switches(_snap(drawdown=-2.1, pnl_daily_pct=-0.5), _limits())
        assert r.passed
        assert r.max_allowed_size is None

    def test_drawdown_at_limit_passes(self):
        # exactly at -25.0 triggers; above (like -24.9) should pass
        r = check_kill_switches(_snap(drawdown=-24.9), _limits())
        assert r.passed

    def test_drawdown_kill_switch_triggers(self):
        r = check_kill_switches(_snap(drawdown=-25.0), _limits())
        assert not r.passed
        assert r.reason == AtlasReason.REJECTED_KILL_SWITCH

    def test_drawdown_well_past_kill_switch(self):
        r = check_kill_switches(_snap(drawdown=-30.0), _limits())
        assert not r.passed

    def test_daily_loss_kill_switch_triggers(self):
        r = check_kill_switches(_snap(pnl_daily_pct=-8.0), _limits())
        assert not r.passed
        assert r.reason == AtlasReason.REJECTED_KILL_SWITCH

    def test_daily_loss_just_below_kill_switch_passes(self):
        r = check_kill_switches(_snap(pnl_daily_pct=-7.99), _limits())
        assert r.passed

    def test_metrics_include_portfolio_state(self):
        r = check_kill_switches(_snap(drawdown=-5.0, pnl_daily_pct=-1.0), _limits())
        assert "portfolio.drawdown_from_peak_pct" in r.metrics
        assert "portfolio.pnl_daily_pct" in r.metrics


# ── check_pnl_halt ────────────────────────────────────────────────────────────

class TestPnlHalt:
    def test_healthy_passes(self):
        r = check_pnl_halt(_snap(pnl_daily_pct=-1.0, pnl_weekly_pct=-2.0, drawdown=-5.0), _limits())
        assert r.passed

    def test_daily_halt_triggers(self):
        r = check_pnl_halt(_snap(pnl_daily_pct=-2.5), _limits())
        assert not r.passed
        assert r.reason == AtlasReason.REJECTED_PNL_HALT_DAILY

    def test_weekly_halt_triggers(self):
        r = check_pnl_halt(_snap(pnl_daily_pct=-1.0, pnl_weekly_pct=-4.0), _limits())
        assert not r.passed
        assert r.reason == AtlasReason.REJECTED_PNL_HALT_WEEKLY

    def test_drawdown_halt_triggers(self):
        r = check_pnl_halt(_snap(drawdown=-12.0), _limits())
        assert not r.passed
        assert r.reason == AtlasReason.REJECTED_DRAWDOWN_HALT

    def test_drawdown_between_halt_and_kill_switch_triggers_halt(self):
        r = check_pnl_halt(_snap(drawdown=-20.0), _limits())
        assert not r.passed
        assert r.reason == AtlasReason.REJECTED_DRAWDOWN_HALT

    def test_daily_halt_checked_before_weekly(self):
        # Both triggered — daily wins (checked first)
        r = check_pnl_halt(_snap(pnl_daily_pct=-2.5, pnl_weekly_pct=-4.0), _limits())
        assert r.reason == AtlasReason.REJECTED_PNL_HALT_DAILY


# ── check_buying_power ────────────────────────────────────────────────────────

class TestBuyingPower:
    def test_within_limit_passes(self):
        r = check_buying_power(Decimal("50000"), _snap(bp_pct=16.0), _limits())
        assert r.passed
        assert r.max_allowed_size is None

    def test_exceeds_limit_fails(self):
        # bp_pct=35%, proposal adds 10% = 45% > 40% limit
        r = check_buying_power(Decimal("100000"), _snap(bp_pct=35.0), _limits())
        assert not r.passed
        assert r.reason == AtlasReason.REJECTED_BP_INSUFFICIENT

    def test_exactly_at_limit_passes(self):
        # bp_pct=30%, proposal adds exactly 10% = 40%
        r = check_buying_power(Decimal("100000"), _snap(bp_pct=30.0), _limits())
        assert r.passed

    def test_macro_event_stricter_limit(self):
        # bp_pct=20%, proposal adds 10% = 30% > macro limit 25%
        r = check_buying_power(Decimal("100000"), _snap(bp_pct=20.0), _limits(), macro_event_active=True)
        assert not r.passed


# ── check_single_name ─────────────────────────────────────────────────────────

class TestSingleName:
    def test_no_existing_position_within_limit(self):
        snap = _snap(positions=[])
        r = check_single_name("AAPL", Decimal("5.0"), snap, _limits())
        assert r.passed
        assert r.max_allowed_size is None

    def test_adding_within_limit_passes(self):
        snap = _snap(positions=[_pos("MSFT", 100, 440.0)])  # 4.4%
        r = check_single_name("MSFT", Decimal("2.0"), snap, _limits())
        # 4.4 + 2.0 = 6.4% < 8% → passes, no reduction
        assert r.passed
        assert r.max_allowed_size is None

    def test_adding_beyond_limit_reduces_size(self):
        snap = _snap(positions=[_pos("MSFT", 100, 440.0)])  # 4.4%
        r = check_single_name("MSFT", Decimal("5.0"), snap, _limits())
        # 4.4 + 5.0 = 9.4% > 8% → reduce to 3.6%
        assert r.passed
        assert r.max_allowed_size is not None
        assert float(r.max_allowed_size) == pytest.approx(3.6, abs=0.01)

    def test_already_at_limit_returns_zero(self):
        snap = _snap(positions=[_pos("MSFT", 182, 440.0)])  # 8.008% ≈ at limit
        r = check_single_name("MSFT", Decimal("1.0"), snap, _limits())
        assert r.max_allowed_size == Decimal("0")

    def test_new_ticker_no_existing_passes(self):
        snap = _snap(positions=[_pos("MSFT", 100, 440.0)])
        r = check_single_name("AAPL", Decimal("5.0"), snap, _limits())
        assert r.passed
        assert r.max_allowed_size is None


# ── check_sector_saturation ───────────────────────────────────────────────────

class TestSectorSaturation:
    def test_other_bucket_always_passes(self):
        snap = _snap(positions=[_pos("XYZ", 100, 100.0)])
        r = check_sector_saturation("ZZZZ", Decimal("5.0"), snap, _limits(), _buckets())
        assert r.passed
        assert r.max_allowed_size is None

    def test_within_sector_limit_passes(self):
        snap = _snap(positions=[_pos("MSFT", 100, 440.0)])  # 4.4% tech
        r = check_sector_saturation("AAPL", Decimal("5.0"), snap, _limits(), _buckets())
        # 4.4 + 5.0 = 9.4% < 30%
        assert r.passed
        assert r.max_allowed_size is None

    def test_sector_over_limit_reduces(self):
        # Create 28% tech exposure already, propose 5% more → reduce
        pos = [_pos("MSFT", 636, 440.0)]  # ~28% of 1M NAV
        snap = _snap(positions=pos)
        r = check_sector_saturation("AAPL", Decimal("5.0"), snap, _limits(), _buckets())
        assert r.passed
        assert r.max_allowed_size is not None
        assert float(r.max_allowed_size) < 5.0

    def test_metrics_include_sector_name(self):
        snap = _snap(positions=[_pos("MSFT", 100, 440.0)])
        r = check_sector_saturation("AAPL", Decimal("2.0"), snap, _limits(), _buckets())
        assert "tech_mega_cap" in str(r.metrics)


# ── check_bucket_saturation ───────────────────────────────────────────────────

class TestBucketSaturation:
    def test_within_bucket_cap_passes(self):
        snap = _snap(positions=[_pos("MSFT", 100, 440.0)])  # 4.4%
        r = check_bucket_saturation("AAPL", Decimal("5.0"), snap, _limits(), _buckets())
        assert r.passed

    def test_other_bucket_always_passes(self):
        snap = _snap(positions=[])
        r = check_bucket_saturation("ZZZZ", Decimal("10.0"), snap, _limits(), _buckets())
        assert r.passed

    def test_beyond_bucket_cap_reduces(self):
        # 44% tech, propose 5% more → exceeds 45% cap
        pos = [_pos("MSFT", 1000, 440.0)]  # 44% of 1M NAV
        snap = _snap(positions=pos)
        r = check_bucket_saturation("AAPL", Decimal("5.0"), snap, _limits(), _buckets())
        assert r.max_allowed_size is not None
        assert float(r.max_allowed_size) == pytest.approx(1.0, abs=0.1)


# ── check_beta ────────────────────────────────────────────────────────────────

class TestBeta:
    def test_zero_beta_contribution_always_passes(self):
        r = check_beta(0.0, _snap(beta=0.82), _limits())
        assert r.passed
        assert r.max_allowed_size is None

    def test_within_range_passes(self):
        r = check_beta(0.1, _snap(beta=0.82), _limits())
        # 0.82 + 0.1 = 0.92 < 1.3
        assert r.passed
        assert r.max_allowed_size is None

    def test_exceeds_beta_max_returns_fraction(self):
        r = check_beta(0.6, _snap(beta=0.82), _limits())
        # 0.82 + 0.6 = 1.42 > 1.3 → fraction = (1.3-0.82)/0.6 = 0.8
        assert "beta_size_fraction_allowed" in r.metrics
        assert r.metrics["beta_size_fraction_allowed"] == pytest.approx(0.8, abs=0.01)

    def test_already_at_beta_max_returns_zero_size(self):
        r = check_beta(0.1, _snap(beta=1.3), _limits())
        assert r.max_allowed_size == Decimal("0")

    def test_negative_beta_contribution_checked_against_min(self):
        r = check_beta(-0.5, _snap(beta=0.0), _limits())
        # 0.0 + (-0.5) = -0.5 < -0.3 → fraction = (0.0 - (-0.3)) / 0.5 = 0.6
        assert "beta_size_fraction_allowed" in r.metrics
        assert r.metrics["beta_size_fraction_allowed"] == pytest.approx(0.6, abs=0.01)

    def test_already_past_beta_min_returns_zero_size(self):
        r = check_beta(-0.1, _snap(beta=-0.3), _limits())
        assert r.max_allowed_size == Decimal("0")


# ── check_vega ────────────────────────────────────────────────────────────────

class TestVega:
    def test_zero_vega_contribution_skipped(self):
        r = check_vega(0.0, Decimal("5.0"), _snap(), _limits())
        assert r.passed
        assert "skipped_no_options" in str(r.metrics)

    def test_within_vega_limit_passes(self):
        # nav=1M, limit=3% → max vega = 30000 USD
        # current_vega = -12400, addition = -5000 → abs post = 17400 < 30000
        r = check_vega(-5000.0, Decimal("5.0"), _snap(vega_total=-12400.0), _limits())
        assert r.passed
        assert r.max_allowed_size is None

    def test_exceeds_vega_limit_reduces_size(self):
        # current_vega = -25000, limit = 30000, addition = -10000
        # headroom = 30000 - 25000 = 5000; fraction = 5000/10000 = 0.5
        r = check_vega(-10000.0, Decimal("10.0"), _snap(vega_total=-25000.0), _limits())
        assert r.passed
        assert r.max_allowed_size is not None
        assert float(r.max_allowed_size) == pytest.approx(5.0, abs=0.01)

    def test_already_at_vega_limit_returns_zero(self):
        r = check_vega(-1000.0, Decimal("5.0"), _snap(vega_total=-30000.0), _limits())
        assert r.max_allowed_size == Decimal("0")

    def test_vega_limit_computed_from_nav(self):
        # Bigger NAV → bigger vega limit
        big_nav_snap = _snap(nav=2_000_000.0, vega_total=-25000.0)
        r = check_vega(-40000.0, Decimal("5.0"), big_nav_snap, _limits(vega_pct=3.0))
        # limit = 2M * 3% = 60000; post = 25000+40000 = 65000 > 60000 → reduces
        assert r.max_allowed_size is not None
        assert float(r.max_allowed_size) < 5.0
