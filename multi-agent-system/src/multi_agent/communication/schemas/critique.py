from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ..base import BaseMessage
from ..enums import MessageType, Stance


class EvidenceItem(BaseModel):
    claim: str
    data_source: str
    value: float | int | str


class CritiqueArgument(BaseModel):
    summary: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    concern: str
    data_that_would_change_my_mind: str


class CritiqueMessage(BaseMessage):
    message_type: Literal[MessageType.CRITIQUE] = MessageType.CRITIQUE
    stance: Stance
    argument: CritiqueArgument
    # dict | None avoids circular import with ProposalMessage; validated at the bus layer
    alternative_proposal: dict | None = None
    veto_request: bool = False
    contrarian_flag_raised: bool = False
