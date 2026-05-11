"""
Snapshot test for ProposalMessage shape (Sprint 3 B.3.7).

Constructs a canonical ProposalMessage and asserts its JSON-mode serialization
matches tests/snapshots/proposal_shape.json byte-for-byte (modulo key ordering).

PURPOSE — schema drift detection:
- Renamed/removed fields → test fails.
- New required fields (without default) → test fails on construction.
- Type changes affecting serialization (Decimal → float, enum case) → test fails.
- Default value changes (e.g., schema_version="1.0" → "2.0") → test fails.

HOW TO REGENERATE THE SNAPSHOT (when schema changes intentionally):
1. Adjust the canonical values in _build_canonical_proposal() if the schema
   added a new field that needs a value here.
2. Run:
       python3 -c "
       from tests.agents.test_proposal_shape_snapshot import _build_canonical_proposal
       import json
       msg = _build_canonical_proposal()
       with open('tests/snapshots/proposal_shape.json', 'w') as f:
           json.dump(msg.model_dump(mode='json'), f, indent=2)
           f.write('\\n')
       "
3. Verify diff manually before committing — the diff IS the schema change.
4. Update the commit message / changelog so the diff has context.

The canonical proposal uses values DIFFERENT from _SHAPE_A_JSON (used in
test_athena_agent.py and test_trades_routes.py) to keep this fixture
independent — accidental coupling between fixtures would mask drift.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from multi_agent.communication.enums import (
    AgentId, AssetClass, Direction, OptionType, StrategyType,
)
from multi_agent.communication.schemas import (
    DataSignature, OptionLeg, ProposalMessage, Thesis,
    TradeDetails, TradeSizing, TradeStructure,
)


_SNAPSHOT_PATH = Path(__file__).parent.parent / "snapshots" / "proposal_shape.json"


def _build_canonical_proposal() -> ProposalMessage:
    """Construct a canonical ProposalMessage with pinned UUIDs and timestamps."""
    return ProposalMessage(
        message_id=UUID("00000000-0000-0000-0000-000000000001"),
        correlation_id=UUID("11111111-1111-1111-1111-111111111111"),
        agent_id=AgentId.ATHENA,
        timestamp=datetime(2026, 5, 11, 15, 0, 0, tzinfo=timezone.utc),
        trade=TradeDetails(
            ticker="QQQ",
            asset_class=AssetClass.OPTION,
            strategy_type=StrategyType.CREDIT_SPREAD,
            structure=TradeStructure(
                legs=[
                    OptionLeg(
                        action=Direction.SELL,
                        instrument_type=OptionType.PUT,
                        strike=Decimal("380.00"),
                        expiration=date(2026, 7, 17),
                        quantity=1,
                    ),
                    OptionLeg(
                        action=Direction.BUY,
                        instrument_type=OptionType.PUT,
                        strike=Decimal("375.00"),
                        expiration=date(2026, 7, 17),
                        quantity=1,
                    ),
                ],
                estimated_credit=Decimal("1.20"),
                estimated_debit=None,
                max_profit=Decimal("1.20"),
                max_loss=Decimal("3.80"),
                breakeven=Decimal("378.80"),
                buying_power_required=Decimal("500.00"),
            ),
        ),
        thesis=Thesis(
            premise="QQQ implied volatility elevated after earnings beat",
            mechanism="Vertical credit spread captures vol premium with defined risk",
            key_data_points=["IV rank 78", "put-call ratio 1.2", "30d realized 22%"],
            invalidation="QQQ closes below long put strike 375",
            target="Close at 70% max profit or expiration",
            time_horizon_days=45,
            expected_holding_period_days=32,
        ),
        conviction_score=65,
        sizing=TradeSizing(
            proposed_size_pct_portfolio=1.5,
            proposed_size_usd=Decimal("15000.00"),
            kelly_suggested=0.20,
            kelly_fraction_applied=0.15,
        ),
        self_acknowledged_biases=["confirmation_bias", "anchoring_to_recent_lows"],
        data_signature=DataSignature(
            data_sources=["stub_data_layer", "test_canonical"],
            data_timestamp=datetime(2026, 5, 11, 14, 30, 0, tzinfo=timezone.utc),
            model_version="athena-snapshot-v1.0",
        ),
    )


def test_proposal_shape_matches_snapshot():
    """Canonical ProposalMessage serializes to the stored snapshot."""
    msg = _build_canonical_proposal()
    actual = msg.model_dump(mode="json")
    with _SNAPSHOT_PATH.open() as f:
        expected = json.load(f)
    # Compare with sort_keys to make the failure diff stable and key-order independent.
    assert json.dumps(actual, sort_keys=True, indent=2) == json.dumps(expected, sort_keys=True, indent=2)
