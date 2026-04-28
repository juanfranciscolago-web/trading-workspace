"""
Tests for shared-core modules.

Focus on the parts that don't require network or database:
- Domain models
- Greeks calculator
- Indicators
- Event serialization
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from shared_core.messaging.event_bus import Event, EventTypes
from shared_core.models import (
    AssetClass,
    Direction,
    Instrument,
    OptionType,
    Position,
    TradeSource,
)
from shared_core.utils.greeks_calculator import (
    BlackScholesInput,
    black_scholes_price,
    calculate_greeks,
    implied_volatility,
    time_to_expiry_years,
)
from shared_core.utils.indicators import (
    average_true_range,
    iv_percentile,
    iv_rank,
    realized_volatility,
    relative_strength,
    relative_volume,
    volatility_risk_premium,
)


# =============================================================================
# Domain models
# =============================================================================

class TestModels:

    def test_instrument_equity(self):
        i = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)
        assert i.occ_symbol is None  # Not an option

    def test_instrument_option_generates_occ_symbol(self):
        i = Instrument(
            symbol="MSFT_PUT_410_2026-06-19",
            asset_class=AssetClass.OPTION,
            option_type=OptionType.PUT,
            strike=Decimal("410"),
            expiration=date(2026, 6, 19),
            underlying="MSFT",
        )
        # OCC: MSFT260619P00410000
        assert i.occ_symbol == "MSFT260619P00410000"

    def test_position_long_short_helpers(self):
        i = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)
        p_long = Position(
            position_id="1",
            source=TradeSource.MULTI_AGENT_ATHENA,
            instrument=i,
            quantity=100,
            entry_price=Decimal("400"),
            entry_timestamp=datetime.now(timezone.utc),
        )
        assert p_long.is_long is True
        assert p_long.is_short is False
        assert p_long.absolute_quantity == 100

        p_short = Position(
            position_id="2",
            source=TradeSource.EOLO_V1,
            instrument=i,
            quantity=-50,
            entry_price=Decimal("400"),
            entry_timestamp=datetime.now(timezone.utc),
        )
        assert p_short.is_short is True
        assert p_short.absolute_quantity == 50

    def test_position_unrealized_pnl_equity(self):
        i = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)
        p = Position(
            position_id="1",
            source=TradeSource.EOLO_V1,
            instrument=i,
            quantity=100,
            entry_price=Decimal("400"),
            entry_timestamp=datetime.now(timezone.utc),
            current_price=Decimal("410"),
        )
        # Long 100 shares, +$10 each = +$1000
        assert p.unrealized_pnl() == Decimal("1000")

    def test_position_unrealized_pnl_option(self):
        i = Instrument(
            symbol="MSFT_OPT",
            asset_class=AssetClass.OPTION,
            option_type=OptionType.PUT,
            strike=Decimal("410"),
            expiration=date(2026, 6, 19),
            underlying="MSFT",
        )
        p = Position(
            position_id="1",
            source=TradeSource.EOLO_V1,
            instrument=i,
            quantity=-10,  # Short 10 contracts
            entry_price=Decimal("4.85"),
            entry_timestamp=datetime.now(timezone.utc),
            current_price=Decimal("2.50"),  # Decreased — good for short seller
        )
        # Short -10 contracts, price went from 4.85 to 2.50, *100 multiplier
        # PnL = (2.50 - 4.85) * 100 * -10 = -2.35 * -1000 = +2350
        assert p.unrealized_pnl() == Decimal("2350")


# =============================================================================
# Greeks calculator
# =============================================================================

class TestGreeksCalculator:

    def test_atm_call_price(self):
        """At-the-money call should have positive but moderate price."""
        inputs = BlackScholesInput(
            underlying_price=100,
            strike=100,
            time_to_expiry_years=0.25,
            risk_free_rate=0.05,
            volatility=0.20,
            option_type="call",
        )
        price = black_scholes_price(inputs)
        # ATM 3-month call at 20% IV ~ $4.61
        assert 4.0 < price < 5.5

    def test_atm_put_price(self):
        """At-the-money put."""
        inputs = BlackScholesInput(
            underlying_price=100,
            strike=100,
            time_to_expiry_years=0.25,
            risk_free_rate=0.05,
            volatility=0.20,
            option_type="put",
        )
        price = black_scholes_price(inputs)
        # ATM 3-month put at 20% IV ~ $3.36
        assert 3.0 < price < 4.0

    def test_call_delta_atm(self):
        """ATM call delta should be near 0.5."""
        inputs = BlackScholesInput(
            underlying_price=100,
            strike=100,
            time_to_expiry_years=0.25,
            risk_free_rate=0.05,
            volatility=0.20,
            option_type="call",
        )
        greeks = calculate_greeks(inputs)
        assert 0.50 <= greeks.delta <= 0.60  # Slightly above 0.5 due to drift

    def test_put_delta_atm(self):
        """ATM put delta should be near -0.5."""
        inputs = BlackScholesInput(
            underlying_price=100,
            strike=100,
            time_to_expiry_years=0.25,
            risk_free_rate=0.05,
            volatility=0.20,
            option_type="put",
        )
        greeks = calculate_greeks(inputs)
        assert -0.50 <= greeks.delta <= -0.40

    def test_implied_vol_round_trip(self):
        """Calculate price, then recover IV from price."""
        original_iv = 0.30
        inputs = BlackScholesInput(
            underlying_price=100,
            strike=100,
            time_to_expiry_years=0.25,
            risk_free_rate=0.05,
            volatility=original_iv,
            option_type="call",
        )
        market_price = black_scholes_price(inputs)
        recovered_iv = implied_volatility(
            market_price=market_price,
            underlying_price=100,
            strike=100,
            time_to_expiry_years=0.25,
            risk_free_rate=0.05,
            option_type="call",
        )
        assert abs(recovered_iv - original_iv) < 0.001

    def test_time_to_expiry_helper(self):
        today = date(2026, 4, 28)
        exp = date(2026, 6, 19)
        years = time_to_expiry_years(today, exp)
        # 52 days / 365
        assert abs(years - 52/365) < 0.001

    def test_greeks_aggregation(self):
        """Aggregate greeks scale correctly with quantity * multiplier."""
        from shared_core.models import Greeks
        per_contract = Greeks(delta=0.5, gamma=0.02, theta=-0.05, vega=0.10)
        agg = per_contract.aggregate(quantity=10, multiplier=100)
        assert agg.delta == 0.5 * 1000
        assert agg.gamma == 0.02 * 1000
        assert agg.theta == -0.05 * 1000


# =============================================================================
# Indicators
# =============================================================================

class TestIndicators:

    def test_iv_rank_at_max(self):
        """If current IV is the max in history, rank should be 100."""
        history = [0.20, 0.25, 0.30, 0.22]
        rank = iv_rank(0.30, history)
        assert rank == 100.0

    def test_iv_rank_at_min(self):
        history = [0.20, 0.25, 0.30, 0.22]
        rank = iv_rank(0.20, history)
        assert rank == 0.0

    def test_iv_rank_middle(self):
        history = [0.10, 0.30]
        rank = iv_rank(0.20, history)
        assert rank == pytest.approx(50.0)

    def test_iv_rank_empty_history(self):
        rank = iv_rank(0.30, [])
        assert rank == 50.0  # Neutral default

    def test_iv_percentile(self):
        history = [0.10, 0.15, 0.20, 0.25, 0.30]
        pct = iv_percentile(0.22, history)
        # 3 out of 5 days are below 0.22
        assert pct == 60.0

    def test_realized_volatility(self):
        # Generate prices with low vol
        prices = [100, 100.5, 100.2, 100.8, 100.3, 100.6]
        rv = realized_volatility(prices)
        # Should be positive, annualized
        assert 0 < rv < 1.0

    def test_vrp(self):
        assert volatility_risk_premium(0.30, 0.20) == pytest.approx(0.10)

    def test_relative_strength(self):
        asset = [100, 110]      # +10%
        benchmark = [100, 105]   # +5%
        rs = relative_strength(asset, benchmark)
        # 1.10 / 1.05 ≈ 1.0476
        assert rs > 1.0
        assert abs(rs - 1.0476) < 0.001

    def test_relative_volume(self):
        assert relative_volume(150_000, 100_000) == 1.5

    def test_atr(self):
        # 3 bars of OHLC
        highs = [100, 102, 101]
        lows = [98, 99, 99]
        closes = [99, 101, 100]
        atr = average_true_range(highs, lows, closes, period=14)
        assert atr > 0


# =============================================================================
# Event serialization
# =============================================================================

class TestEvents:

    def test_event_round_trip(self):
        original = Event(
            event_type=EventTypes.TRADE_EXECUTED,
            source="eolo_v1",
            payload={"ticker": "MSFT", "quantity": 100},
        )
        json_str = original.to_json()
        recovered = Event.from_json(json_str)

        assert recovered.event_type == original.event_type
        assert recovered.source == original.source
        assert recovered.payload == original.payload
