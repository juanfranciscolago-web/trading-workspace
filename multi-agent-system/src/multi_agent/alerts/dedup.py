"""
AlertDedup — Redis SET NX + EX dedup windows per event type.

Dedup key patterns and TTLs:
  position.margin_breach   → alerts:dedup:margin:{symbol}           30 min
  position.stop_loss_hit   → alerts:dedup:stop:{position_id}        365 days (never re-fire)
  system.failure           → alerts:dedup:sys:{component}           5 min
  position.roll_opportunity→ alerts:dedup:roll:{position_id}:{date} 24h

is_duplicate() returns True if the event was already seen in the window.
If True, the caller should skip dispatching to any sink.
"""
from __future__ import annotations

import logging
import os

from .events import AlertEvent, AlertEventType

logger = logging.getLogger(__name__)

# TTL in seconds per event type
_TTL: dict[str, int] = {
    AlertEventType.MARGIN_BREACH.value:    1_800,       # 30 min
    AlertEventType.STOP_LOSS_HIT.value:    31_536_000,  # 365 days (effectively permanent)
    AlertEventType.SYSTEM_FAILURE.value:   300,         # 5 min
    AlertEventType.ROLL_OPPORTUNITY.value: 86_400,      # 24h
}


def make_dedup_key(event: AlertEvent) -> str:
    """Derive the Redis dedup key from an event's type and payload fields."""
    t = event.event_type.value
    p = event.payload
    if t == AlertEventType.MARGIN_BREACH.value:
        return f"alerts:dedup:margin:{p.get('symbol', 'unknown')}"
    if t == AlertEventType.STOP_LOSS_HIT.value:
        return f"alerts:dedup:stop:{p.get('position_id', 'unknown')}"
    if t == AlertEventType.SYSTEM_FAILURE.value:
        return f"alerts:dedup:sys:{p.get('component', 'unknown')}"
    if t == AlertEventType.ROLL_OPPORTUNITY.value:
        date = p.get("expiry_date", "unknown")
        return f"alerts:dedup:roll:{p.get('position_id', 'unknown')}:{date}"
    return f"alerts:dedup:generic:{t}"


class AlertDedup:

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client

    def _get_client(self):
        if self._redis is not None:
            return self._redis
        import redis as _redis
        return _redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )

    def is_duplicate(self, event: AlertEvent) -> tuple[bool, str]:
        """
        Check whether this event is a duplicate within its dedup window.

        Returns (is_dup, dedup_key).
        SET NX EX: first call sets the key → not a dup.
        Subsequent calls within TTL → dup, skip sink.
        """
        key = make_dedup_key(event)
        ttl = _TTL.get(event.event_type.value, 300)
        try:
            client = self._get_client()
            # SET key "1" NX EX ttl — returns True if key was newly set
            was_set = client.set(key, "1", nx=True, ex=ttl)
            is_dup = not was_set
            if is_dup:
                logger.debug("AlertDedup hit key=%s", key)
            return is_dup, key
        except Exception:
            logger.exception("AlertDedup.is_duplicate failed — treating as NOT duplicate")
            # Fail open for dedup: better to send a duplicate than to silence an alert
            return False, key
