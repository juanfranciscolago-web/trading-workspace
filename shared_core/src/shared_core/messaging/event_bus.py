"""
Cross-system event bus using Redis pub/sub.

Both Eolo and multi-agent publish/subscribe to the same channels for
coordination. This avoids tight coupling — neither system needs to know
the other's internals, just the event contract.

Channels:
    system_events       — high-level events (trade opened, closed, mode change)
    risk_events         — ATLAS alerts (limit breaches, mode transitions)
    market_data_alerts  — significant price moves, news triggers
    tool_requests       — multi-agent invoking Eolo as tool (Phase 2+)
    tool_responses      — Eolo responding to tool requests
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Event types
# =============================================================================

@dataclass
class Event:
    """Base event — all events serialize to JSON via this."""
    event_type: str
    source: str  # "eolo_v1", "multi_agent", "atlas", etc.
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    correlation_id: Optional[str] = None
    payload: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> Event:
        data = json.loads(raw)
        return cls(**data)


# =============================================================================
# Publisher
# =============================================================================

class EventPublisher:
    """Publish events to Redis channels."""

    def __init__(self, redis_client):
        self._redis = redis_client

    @classmethod
    def from_env(cls) -> EventPublisher:
        redis_client = _get_redis_from_env()
        return cls(redis_client)

    def publish(self, channel: str, event: Event) -> int:
        """
        Publish an event to a channel.

        Returns:
            Number of subscribers that received the message.
        """
        payload = event.to_json()
        try:
            count = self._redis.publish(channel, payload)
            logger.debug(f"Published {event.event_type} to {channel} ({count} receivers)")
            return count
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")
            return 0


# =============================================================================
# Subscriber
# =============================================================================

class EventSubscriber:
    """Subscribe to Redis channels and dispatch events to handlers."""

    def __init__(self, redis_client):
        self._redis = redis_client
        self._pubsub = redis_client.pubsub()
        self._handlers: dict[str, list[Callable[[Event], None]]] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False

    @classmethod
    def from_env(cls) -> EventSubscriber:
        redis_client = _get_redis_from_env()
        return cls(redis_client)

    def subscribe(
        self,
        channel: str,
        handler: Callable[[Event], None],
    ) -> None:
        """Register a handler for a channel."""
        if channel not in self._handlers:
            self._handlers[channel] = []
            self._pubsub.subscribe(channel)
        self._handlers[channel].append(handler)
        logger.info(f"Subscribed handler to channel: {channel}")

    def start(self) -> None:
        """Start listening in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info("EventSubscriber started")

    def stop(self) -> None:
        """Stop listening."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._pubsub.close()
        logger.info("EventSubscriber stopped")

    def _listen_loop(self) -> None:
        """Background thread that processes incoming messages."""
        while self._running:
            try:
                message = self._pubsub.get_message(timeout=1.0)
                if message is None or message.get("type") != "message":
                    continue

                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode("utf-8")

                raw_data = message["data"]
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8")

                try:
                    event = Event.from_json(raw_data)
                except Exception as e:
                    logger.error(f"Failed to parse event: {e} | data={raw_data}")
                    continue

                handlers = self._handlers.get(channel, [])
                for handler in handlers:
                    try:
                        handler(event)
                    except Exception as e:
                        logger.exception(f"Handler raised on event {event.event_type}: {e}")

            except Exception as e:
                logger.exception(f"Listen loop error: {e}")


# =============================================================================
# Helpers
# =============================================================================

def _get_redis_from_env():
    """Lazy-load redis to avoid hard dependency."""
    try:
        import redis
    except ImportError:
        raise RuntimeError("redis-py not installed. Run: pip install redis")

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return redis.from_url(redis_url, decode_responses=False)


# =============================================================================
# Standard event types (constants used across systems)
# =============================================================================

class EventTypes:
    # Trade lifecycle
    TRADE_PROPOSED = "trade.proposed"
    TRADE_APPROVED = "trade.approved"
    TRADE_BLOCKED = "trade.blocked"
    TRADE_EXECUTED = "trade.executed"
    TRADE_CLOSED = "trade.closed"

    # Risk events
    RISK_MODE_CHANGED = "risk.mode_changed"
    RISK_LIMIT_BREACHED = "risk.limit_breached"
    RISK_HEDGE_REQUIRED = "risk.hedge_required"

    # Market events
    MARKET_VOLATILITY_SPIKE = "market.volatility_spike"
    MARKET_HALT = "market.halt"

    # System events
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"

    # Tool requests (Phase 2+)
    TOOL_REQUEST = "tool.request"
    TOOL_RESPONSE = "tool.response"


class Channels:
    SYSTEM_EVENTS = "system_events"
    RISK_EVENTS = "risk_events"
    MARKET_DATA_ALERTS = "market_data_alerts"
    TOOL_REQUESTS = "tool_requests"
    TOOL_RESPONSES = "tool_responses"
