from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from .enums import AgentId, MessageType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class BaseMessage(BaseModel):
    """Root of the multi-agent message hierarchy. All messages are immutable once created."""

    model_config = ConfigDict(frozen=True)

    message_id: UUID = Field(default_factory=uuid4)
    message_type: MessageType
    timestamp: datetime = Field(default_factory=_utcnow)
    agent_id: AgentId
    schema_version: str = "1.0"
    correlation_id: UUID = Field(default_factory=uuid4)
    parent_message_id: UUID | None = None
