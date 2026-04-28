from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from ..base import BaseMessage
from ..enums import AssetClass, Direction, MessageType, OptionType, StrategyType


class OptionLeg(BaseModel):
    action: Direction
    instrument_type: OptionType
    strike: Decimal
    expiration: date
    quantity: int = Field(gt=0)


class TradeStructure(BaseModel):
    legs: list[OptionLeg] = Field(min_length=1)
    estimated_credit: Decimal | None = None
    estimated_debit: Decimal | None = None
    max_profit: Decimal | None = None
    max_loss: Decimal | None = None
    breakeven: Decimal | None = None
    buying_power_required: Decimal = Field(gt=0)


class TradeDetails(BaseModel):
    ticker: str
    asset_class: AssetClass
    strategy_type: StrategyType
    structure: TradeStructure


class Thesis(BaseModel):
    premise: str
    mechanism: str
    key_data_points: list[str] = Field(min_length=1)
    invalidation: str
    target: str
    time_horizon_days: int = Field(gt=0)
    expected_holding_period_days: int = Field(gt=0)


class TradeSizing(BaseModel):
    proposed_size_pct_portfolio: float = Field(gt=0, le=100)
    proposed_size_usd: Decimal = Field(gt=0)
    kelly_suggested: float = Field(ge=0)
    kelly_fraction_applied: float = Field(gt=0, le=1.0)


class DataSignature(BaseModel):
    data_sources: list[str] = Field(min_length=1)
    data_timestamp: datetime
    model_version: str


class ProposalMessage(BaseMessage):
    message_type: Literal[MessageType.PROPOSAL] = MessageType.PROPOSAL
    trade: TradeDetails
    thesis: Thesis
    conviction_score: int = Field(ge=0, le=100)
    sizing: TradeSizing
    self_acknowledged_biases: list[str] = Field(default_factory=list)
    data_signature: DataSignature
