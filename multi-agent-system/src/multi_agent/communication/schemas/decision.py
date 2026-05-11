from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..base import BaseMessage
from ..enums import AgentId, ConsensusType, DecisionOutcome, MessageType


class ConsensusState(BaseModel):
    agree: list[AgentId] = Field(default_factory=list)
    disagree: list[AgentId] = Field(default_factory=list)
    neutral: list[AgentId] = Field(default_factory=list)
    consensus_type: ConsensusType


class SizeModulation(BaseModel):
    original_size_pct: float = Field(gt=0)
    approved_size_pct: float = Field(gt=0)
    reduction_reason: str


class AtlasValidationRef(BaseModel):
    """Placeholder tracking ATLAS validation state at decision time."""
    status: str = "PENDING"


class DecisionMessage(BaseMessage):
    message_type: Literal[MessageType.DECISION] = MessageType.DECISION
    outcome: DecisionOutcome
    consensus_state: ConsensusState
    size_modulation: SizeModulation | None = None
    conditions: list[str] = Field(default_factory=list)
    atlas_validation: AtlasValidationRef = Field(default_factory=AtlasValidationRef)
    contrarian_flag_raised: bool = False
