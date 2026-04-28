"""
ATHENA mock — systematic quant agent.

Generates a cash-secured put (or iron condor) proposal based on the scenario.
Strike is derived from mock_price with small seeded variation.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from multi_agent.communication.enums import (
    AgentId,
    AssetClass,
    Direction,
    OptionType,
    StrategyType,
)
from multi_agent.communication.schemas import (
    DataSignature,
    OptionLeg,
    ProposalMessage,
    Thesis,
    TradeDetails,
    TradeSizing,
    TradeStructure,
)

from .base import BaseMockAgent
from .fixtures import ScenarioDef

# Simulated portfolio NAV for sizing calculations
_MOCK_NAV_USD = 1_000_000.0


def _csp_structure(
    mock_price: float,
    rng: random.Random,
    expiry: date,
) -> TradeStructure:
    """Sell 1 put at ~95% of current price."""
    moneyness = rng.uniform(0.93, 0.97)
    raw_strike = mock_price * moneyness
    # Round to nearest $5 increment
    strike = Decimal(str(round(raw_strike / 5) * 5))
    credit = Decimal(str(round(rng.uniform(2.8, 4.5), 2)))
    bpr = strike * 100  # cash-secured = full strike value per contract

    leg = OptionLeg(
        action=Direction.SELL,
        instrument_type=OptionType.PUT,
        strike=strike,
        expiration=expiry,
        quantity=1,
    )
    return TradeStructure(
        legs=[leg],
        estimated_credit=credit,
        max_profit=credit,
        max_loss=strike - credit,
        breakeven=strike - credit,
        buying_power_required=bpr,
    )


def _iron_condor_structure(
    mock_price: float,
    rng: random.Random,
    expiry: date,
) -> TradeStructure:
    """Sell OTM put spread + call spread."""
    put_short_strike = Decimal(str(round(mock_price * rng.uniform(0.93, 0.96) / 5) * 5))
    put_long_strike = put_short_strike - 5
    call_short_strike = Decimal(str(round(mock_price * rng.uniform(1.04, 1.07) / 5) * 5))
    call_long_strike = call_short_strike + 5
    credit = Decimal(str(round(rng.uniform(1.5, 2.8), 2)))
    bpr = Decimal("500")  # $5-wide spread max loss

    legs = [
        OptionLeg(action=Direction.SELL, instrument_type=OptionType.PUT,
                  strike=put_short_strike, expiration=expiry, quantity=1),
        OptionLeg(action=Direction.BUY, instrument_type=OptionType.PUT,
                  strike=put_long_strike, expiration=expiry, quantity=1),
        OptionLeg(action=Direction.SELL, instrument_type=OptionType.CALL,
                  strike=call_short_strike, expiration=expiry, quantity=1),
        OptionLeg(action=Direction.BUY, instrument_type=OptionType.CALL,
                  strike=call_long_strike, expiration=expiry, quantity=1),
    ]
    return TradeStructure(
        legs=legs,
        estimated_credit=credit,
        max_profit=credit,
        max_loss=Decimal("500") - credit,
        buying_power_required=bpr,
    )


class AthenaMock(BaseMockAgent):
    agent_id = AgentId.ATHENA

    def generate_proposal(
        self,
        scenario: ScenarioDef,
        rng: random.Random,
        correlation_id: UUID,
    ) -> ProposalMessage:
        # Target expiry ~30 DTE from today
        today = date.today()
        dte = rng.randint(28, 38)
        expiry = date.fromordinal(today.toordinal() + dte)

        if scenario.strategy_type == StrategyType.IRON_CONDOR:
            structure = _iron_condor_structure(scenario.mock_price, rng, expiry)
        else:
            structure = _csp_structure(scenario.mock_price, rng, expiry)

        trade = TradeDetails(
            ticker=scenario.ticker,
            asset_class=scenario.asset_class,
            strategy_type=scenario.strategy_type,
            structure=structure,
        )

        thesis = Thesis(
            premise=(
                f"{scenario.ticker} IV is elevated relative to 30-day realized vol, "
                "creating favorable premium capture opportunity."
            ),
            mechanism=(
                f"Sell {scenario.strategy_type.value} at ~{int(scenario.mock_price * 0.95)}"
                f" strike; collect theta decay over {dte}-day period."
            ),
            key_data_points=[
                f"IV rank: {rng.randint(55, 80)}th percentile",
                f"30-day realized vol: {round(rng.uniform(16, 24), 1)}%",
                f"Expected move: ±{round(rng.uniform(3, 6), 1)}%",
            ],
            invalidation=(
                f"{scenario.ticker} closes below short strike; "
                "IV spikes above 40%; earnings announcement within DTE."
            ),
            target=f"Collect {float(structure.estimated_credit or 3.0):.2f}/contract; expire worthless",
            time_horizon_days=dte,
            expected_holding_period_days=dte,
        )

        proposed_usd = Decimal(str(round(_MOCK_NAV_USD * scenario.proposed_size_pct / 100)))
        kelly = round(rng.uniform(0.20, 0.35), 2)

        sizing = TradeSizing(
            proposed_size_pct_portfolio=scenario.proposed_size_pct,
            proposed_size_usd=proposed_usd,
            kelly_suggested=kelly,
            kelly_fraction_applied=0.5,
        )

        return ProposalMessage(
            agent_id=AgentId.ATHENA,
            correlation_id=correlation_id,
            trade=trade,
            thesis=thesis,
            conviction_score=scenario.conviction_score,
            sizing=sizing,
            self_acknowledged_biases=["recency_bias_on_IV", "anchoring_to_prior_strikes"],
            data_signature=DataSignature(
                data_sources=["yahoo_finance_options", "cboe_iv_index"],
                data_timestamp=datetime.now(timezone.utc),
                model_version="athena-mock-v1.0",
            ),
        )
