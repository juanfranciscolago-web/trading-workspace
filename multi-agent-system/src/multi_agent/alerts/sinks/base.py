"""Base sink ABC — all notification sinks implement this interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..events import AlertEvent


class BaseSink(ABC):

    @abstractmethod
    async def send(self, event: AlertEvent, text: str) -> str | None:
        """
        Send a formatted alert to this sink.

        Returns a sink-specific message ID (e.g. Telegram message_id as str)
        if the message was delivered successfully, or None on failure.
        Implementations must not raise — log errors and return None.
        """
        ...
