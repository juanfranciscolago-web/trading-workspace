from __future__ import annotations

from .base import BaseMessage
from .enums import MessageType
from .schemas.atlas_validation import AtlasValidationMessage
from .schemas.critique import CritiqueMessage
from .schemas.decision import DecisionMessage
from .schemas.execution import ExecutionMessage
from .schemas.postmortem import PostmortemMessage
from .schemas.proposal import ProposalMessage

_REGISTRY: dict[str, type[BaseMessage]] = {
    MessageType.PROPOSAL.value: ProposalMessage,
    MessageType.CRITIQUE.value: CritiqueMessage,
    MessageType.DECISION.value: DecisionMessage,
    MessageType.ATLAS_VALIDATION.value: AtlasValidationMessage,
    MessageType.EXECUTION.value: ExecutionMessage,
    MessageType.POSTMORTEM.value: PostmortemMessage,
}


def deserialize_message(data: dict) -> BaseMessage:
    """Deserialize a raw dict into the correct message subclass by message_type."""
    msg_type = data.get("message_type")
    if msg_type is None:
        raise ValueError("Missing 'message_type' field")
    model_cls = _REGISTRY.get(str(msg_type))
    if model_cls is None:
        raise ValueError(f"Unknown message_type: {msg_type!r}")
    return model_cls.model_validate(data)
