from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..base import BaseMessage
from ..enums import AgentId, MessageType, TradeResult


class TradeOutcome(BaseModel):
    result: TradeResult
    pl_usd: float
    pl_pct_portfolio: float
    holding_period_days: int = Field(ge=0)
    exit_reason: str


class ThesisEvaluation(BaseModel):
    premise_validated: bool
    mechanism_worked_as_expected: bool
    invalidation_triggered: bool
    lessons: list[str] = Field(default_factory=list)


class DissentEvaluation(BaseModel):
    dissenting_agent: AgentId
    dissent_validated: bool
    validation_reasoning: str
    trust_score_adjustment: float = Field(ge=-1.0, le=1.0)


class CalibrationUpdate(BaseModel):
    predicted_pop: int = Field(ge=0, le=100)
    actual_outcome: str
    brier_score_contribution: float = Field(ge=0.0, le=1.0)


class PostmortemMessage(BaseMessage):
    message_type: Literal[MessageType.POSTMORTEM] = MessageType.POSTMORTEM
    trade_owner: AgentId
    outcome: TradeOutcome
    thesis_evaluation: ThesisEvaluation
    dissent_evaluation: list[DissentEvaluation] = Field(default_factory=list)
    calibration_update: CalibrationUpdate
