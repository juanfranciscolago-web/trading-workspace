"""
AlertBus — Redis pub/sub transport for alert events.

Two clients, same channel:
- Sync publish() → called from AtlasConsumer (sync thread)
- Async subscribe() → called from AlertWorker (asyncio task)

Channel: alerts:events
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

ALERTS_CHANNEL = "alerts:events"


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")


class AlertBus:

    def publish(self, event) -> int:
        """
        Publish AlertEvent to Redis channel (sync).

        Returns number of subscribers that received the message (0 if
        Redis is unavailable — publish failures are logged but not raised
        so that the calling trade cycle is not interrupted).
        """
        import redis as _redis
        try:
            client = _redis.from_url(_redis_url(), decode_responses=True)
            payload = event.model_dump_json()
            count = client.publish(ALERTS_CHANNEL, payload)
            logger.debug("AlertBus.publish event=%s subscribers=%d", event.event_type, count)
            return count
        except Exception:
            logger.exception("AlertBus.publish failed — alert dropped event=%s", event.event_type)
            return 0

    async def subscribe(self):
        """
        Async generator that yields AlertEvent objects from the Redis channel.

        Reconnects automatically on disconnect. Yields None on timeout
        (allows caller to check for shutdown signal).
        """
        import redis.asyncio as _aioredis
        from .events import AlertEvent

        client = _aioredis.from_url(_redis_url(), decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(ALERTS_CHANNEL)
        logger.info("AlertBus subscribed to channel %s", ALERTS_CHANNEL)

        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message is None:
                    yield None
                    continue
                try:
                    event = AlertEvent.model_validate_json(message["data"])
                    yield event
                except Exception:
                    logger.exception(
                        "AlertBus: failed to parse message — skipping. data=%r",
                        message.get("data"),
                    )
        finally:
            await pubsub.unsubscribe(ALERTS_CHANNEL)
            await client.aclose()
            logger.info("AlertBus unsubscribed from %s", ALERTS_CHANNEL)
