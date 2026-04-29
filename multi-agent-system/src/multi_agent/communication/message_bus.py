"""
Agent-to-agent message bus backed by Redis Streams.

Architecture:
- STREAMS (this module): persistent, ACK-based, fan-out via consumer groups.
  Used for the critical flow: proposals → critiques → decisions → atlas → execution.
- PUB/SUB (shared_core.messaging.event_bus): ephemeral, fire-and-forget.
  Used for system_events, risk_events, dashboard_notifications.

Each call to subscribe() creates a dedicated daemon thread that runs
XREADGROUP in blocking mode. Messages are ACKed only after the handler
returns without raising (ack-after-success). Failures are retried up to
max_retries; exhausted messages are moved to a dead-letter stream and a
SYSTEM_ERROR is emitted on the shared event bus.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from .base import BaseMessage
from .factory import deserialize_message

logger = logging.getLogger(__name__)

# ── Stream configuration ──────────────────────────────────────────────────────

STREAM_MAXLEN = 50_000       # approximate cap per stream (~50k entries)
BLOCK_MS = 1_000             # XREADGROUP blocking timeout per poll cycle
BATCH_SIZE = 10              # messages read per XREADGROUP call
MAX_RETRIES_DEFAULT = 3      # handler failures before DLQ


# ── Public constants ──────────────────────────────────────────────────────────

class AgentChannels:
    """Stream names for agent-to-agent communication."""
    PROPOSALS       = "agent.proposals"
    CRITIQUES       = "agent.critiques"
    DECISIONS       = "agent.decisions"
    ATLAS_VALIDATION = "agent.atlas_validations"
    EXECUTION       = "agent.executions"
    POSTMORTEM      = "agent.postmortems"

    @staticmethod
    def dead_letter(channel: str) -> str:
        return f"{channel}.dead_letter"


class ConsumerGroups:
    """Predefined consumer group names (one group = one logical reader role)."""
    ATLAS_VALIDATOR = "atlas_validator"
    CRITIQUE_ENGINE  = "critique_engine"
    AUDIT_LOGGER    = "audit_logger"
    DASHBOARD       = "dashboard"


# ── Internal dataclass ────────────────────────────────────────────────────────

@dataclass
class _Subscription:
    channel: str
    consumer_group: str
    consumer_name: str
    handler: Callable[[BaseMessage], None]
    max_retries: int = MAX_RETRIES_DEFAULT
    # mutable state — not part of public API
    _retry_counts: dict[str, int] = field(default_factory=dict, repr=False)
    # local retry queue: entries that failed but haven't exhausted max_retries yet
    _pending_retries: deque = field(default_factory=deque, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)


# ── Bus ───────────────────────────────────────────────────────────────────────

class AgentMessageBus:
    """
    Streams-based message bus for agent-to-agent communication.

    Usage::

        bus = AgentMessageBus.from_env()
        bus.subscribe(
            AgentChannels.PROPOSALS,
            ConsumerGroups.ATLAS_VALIDATOR,
            consumer_name="atlas-1",
            handler=my_handler,
        )
        bus.start()
        bus.publish(AgentChannels.PROPOSALS, proposal_msg)
        # ... later ...
        bus.stop()

    event_publisher: optional shared_core.messaging.event_bus.EventPublisher.
    If provided, a SYSTEM_ERROR is emitted to system_events whenever a message
    is sent to the DLQ.
    """

    def __init__(self, redis_client, event_publisher=None) -> None:
        self._redis = redis_client
        self._event_publisher = event_publisher
        self._subscriptions: list[_Subscription] = []
        self._running = False

    @classmethod
    def from_env(cls) -> AgentMessageBus:
        """Construct from REDIS_URL env var (default: redis://localhost:6379/0)."""
        try:
            import redis
        except ImportError:
            raise RuntimeError("redis-py not installed. Run: pip install redis")
        from multi_agent.config import settings
        return cls(redis.from_url(settings.REDIS_URL, decode_responses=False))

    # ── Publishing ────────────────────────────────────────────────────────────

    def publish(self, channel: str, message: BaseMessage) -> str | bytes:
        """
        Serialize and XADD to stream.

        Two fields are stored:
        - ``message_type``: plain string for easy inspection via redis-cli.
        - ``payload``: full Pydantic JSON (source of truth for deserialization).

        Returns the Redis stream entry ID.
        """
        entry_id = self._redis.xadd(
            channel,
            {
                "message_type": message.message_type.value,
                "payload": message.model_dump_json(),
            },
            maxlen=STREAM_MAXLEN,
            approximate=True,
        )
        logger.debug(
            "Published %s to %s (entry=%s)", message.message_type, channel, entry_id
        )
        return entry_id

    # ── Subscribing ───────────────────────────────────────────────────────────

    def subscribe(
        self,
        channel: str,
        consumer_group: str,
        consumer_name: str,
        handler: Callable[[BaseMessage], None],
        max_retries: int = MAX_RETRIES_DEFAULT,
    ) -> None:
        """
        Register a handler for (channel, consumer_group).

        Creates the consumer group in Redis if it does not exist yet.
        If the bus is already running, starts a thread immediately.
        """
        self._ensure_group(channel, consumer_group)
        sub = _Subscription(
            channel=channel,
            consumer_group=consumer_group,
            consumer_name=consumer_name,
            handler=handler,
            max_retries=max_retries,
        )
        self._subscriptions.append(sub)
        logger.info(
            "Subscribed %s/%s to %s", consumer_group, consumer_name, channel
        )
        if self._running:
            self._start_thread(sub)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start one daemon thread per registered subscription."""
        if self._running:
            return
        self._running = True
        for sub in self._subscriptions:
            self._start_thread(sub)
        logger.info(
            "AgentMessageBus started (%d subscriptions)", len(self._subscriptions)
        )

    def stop(self) -> None:
        """Signal all threads to stop and join them (up to 3 s each)."""
        self._running = False
        for sub in self._subscriptions:
            if sub._thread:
                sub._thread.join(timeout=3.0)
        logger.info("AgentMessageBus stopped")

    # ── Thread management ─────────────────────────────────────────────────────

    def _start_thread(self, sub: _Subscription) -> None:
        name = f"AgentBus:{sub.channel}:{sub.consumer_group}"
        sub._thread = threading.Thread(
            target=self._consume_loop, args=(sub,), daemon=True, name=name
        )
        sub._thread.start()

    # ── Consume loop ──────────────────────────────────────────────────────────

    def _consume_loop(self, sub: _Subscription) -> None:
        # On startup: drain any messages this consumer left un-ACKed previously.
        self._drain_pending(sub)

        while self._running:
            # Flush local retry queue before reading new messages.
            # Entries here failed their handler but haven't exhausted max_retries.
            while sub._pending_retries and self._running:
                entry_id, fields = sub._pending_retries.popleft()
                self._process_entry(sub, entry_id, fields)

            try:
                results = self._redis.xreadgroup(
                    sub.consumer_group,
                    sub.consumer_name,
                    {sub.channel: ">"},   # ">" = new, undelivered messages only
                    count=BATCH_SIZE,
                    block=BLOCK_MS,
                )
            except Exception:
                logger.exception(
                    "xreadgroup error on %s/%s", sub.channel, sub.consumer_group
                )
                continue

            if not results:
                continue

            for _stream, entries in results:
                for entry_id, fields in entries:
                    self._process_entry(sub, entry_id, fields)

    def _drain_pending(self, sub: _Subscription) -> None:
        """
        Read messages previously delivered to this consumer but not ACKed
        (the Pending Entry List). Happens once at thread startup to recover
        from crashes mid-processing.
        """
        try:
            results = self._redis.xreadgroup(
                sub.consumer_group,
                sub.consumer_name,
                {sub.channel: "0"},   # "0" = read from PEL start
                count=BATCH_SIZE,
            )
        except Exception:
            logger.exception(
                "Failed to read PEL on %s/%s", sub.channel, sub.consumer_group
            )
            return

        if not results:
            return

        for _stream, entries in results:
            if entries:
                logger.info(
                    "Replaying %d pending message(s) on %s/%s",
                    len(entries), sub.channel, sub.consumer_group,
                )
            for entry_id, fields in entries:
                self._process_entry(sub, entry_id, fields)

    # ── Entry processing ──────────────────────────────────────────────────────

    def _process_entry(
        self, sub: _Subscription, entry_id: bytes | str, fields: dict
    ) -> None:
        raw = fields.get(b"payload") or fields.get("payload", b"")
        if isinstance(raw, bytes):
            raw = raw.decode()

        # Deserialize
        try:
            message = deserialize_message(json.loads(raw))
        except Exception:
            logger.exception(
                "Cannot deserialize entry=%s on %s — routing to DLQ", entry_id, sub.channel
            )
            self._to_dlq(sub, entry_id, raw, "deserialization_error")
            self._ack(sub, entry_id)
            return

        # Dispatch to handler
        try:
            sub.handler(message)
            self._ack(sub, entry_id)
            sub._retry_counts.pop(str(entry_id), None)
        except Exception:
            retry_key = str(entry_id)
            attempt = sub._retry_counts.get(retry_key, 0) + 1
            sub._retry_counts[retry_key] = attempt
            logger.warning(
                "Handler failed (attempt %d/%d) entry=%s on %s/%s",
                attempt, sub.max_retries, entry_id, sub.channel, sub.consumer_group,
            )
            if attempt >= sub.max_retries:
                logger.error(
                    "DLQ — entry=%s exhausted %d retries on %s/%s",
                    entry_id, sub.max_retries, sub.channel, sub.consumer_group,
                )
                self._to_dlq(sub, entry_id, raw, "max_retries_exceeded")
                self._ack(sub, entry_id)
                sub._retry_counts.pop(retry_key, None)
            else:
                # Enqueue for retry on the next loop iteration (stays in PEL until ACKed)
                sub._pending_retries.append((entry_id, fields))

    # ── ACK ───────────────────────────────────────────────────────────────────

    def _ack(self, sub: _Subscription, entry_id: bytes | str) -> None:
        try:
            self._redis.xack(sub.channel, sub.consumer_group, entry_id)
        except Exception:
            logger.exception(
                "XACK failed for entry=%s on %s/%s",
                entry_id, sub.channel, sub.consumer_group,
            )

    # ── Dead letter ───────────────────────────────────────────────────────────

    def _to_dlq(
        self,
        sub: _Subscription,
        entry_id: bytes | str,
        raw_payload: str,
        reason: str,
    ) -> None:
        dlq = AgentChannels.dead_letter(sub.channel)

        # 1. Write to dead-letter stream
        try:
            self._redis.xadd(
                dlq,
                {
                    "original_channel": sub.channel,
                    "consumer_group": sub.consumer_group,
                    "original_entry_id": str(entry_id),
                    "reason": reason,
                    "payload": raw_payload,
                },
                maxlen=STREAM_MAXLEN,
                approximate=True,
            )
        except Exception:
            logger.exception("Failed to write to DLQ %s", dlq)

        # 2. Structured log — must never be silent
        logger.error(
            "DLQ write | channel=%s group=%s entry=%s reason=%s dlq=%s",
            sub.channel, sub.consumer_group, entry_id, reason, dlq,
        )

        # 3. Emit SYSTEM_ERROR on the shared Pub/Sub bus (if wired up)
        if self._event_publisher is not None:
            self._emit_system_error(sub, entry_id, dlq, reason)

    def _emit_system_error(
        self,
        sub: _Subscription,
        entry_id: bytes | str,
        dlq: str,
        reason: str,
    ) -> None:
        try:
            from shared_core.messaging.event_bus import Channels, Event, EventTypes
            self._event_publisher.publish(
                Channels.SYSTEM_EVENTS,
                Event(
                    event_type=EventTypes.SYSTEM_ERROR,
                    source="agent_message_bus",
                    payload={
                        "dlq_channel": dlq,
                        "original_channel": sub.channel,
                        "consumer_group": sub.consumer_group,
                        "entry_id": str(entry_id),
                        "reason": reason,
                    },
                ),
            )
        except Exception:
            logger.exception("Failed to emit SYSTEM_ERROR for DLQ event on %s", dlq)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _ensure_group(self, channel: str, group: str) -> None:
        """Create consumer group if it doesn't exist (BUSYGROUP = already exists, ok)."""
        try:
            self._redis.xgroup_create(channel, group, id="$", mkstream=True)
            logger.info("Created consumer group %s on %s", group, channel)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise
