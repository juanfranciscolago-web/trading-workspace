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
        if the message was delivered successfully.

        Returns None if this sink is explicitly not applicable or not
        configured for this event (caller will try the next sink in chain).

        Raises on delivery failure after all retries — callers capture the
        exception and record str(exc) as error_msg so failures are actionable.
        """
        ...
