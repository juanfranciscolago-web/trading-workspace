from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from ..base import BaseMessage
from ..enums import MessageType, TradeStatus


class FillRecord(BaseModel):
    leg: int = Field(ge=1)
    fill_price: Decimal
    fill_quantity: int = Field(gt=0)
    fill_timestamp: datetime
    venue: str = "SCHWAB"


class SlippageInfo(BaseModel):
    expected_credit: Decimal
    actual_credit: Decimal
    slippage_pct: float


class ExecutionMessage(BaseMessage):
    message_type: Literal[MessageType.EXECUTION] = MessageType.EXECUTION
    execution_status: TradeStatus
    fills: list[FillRecord] = Field(min_length=1)
    slippage_vs_proposal: SlippageInfo | None = None
    execution_time_ms: int | None = None
