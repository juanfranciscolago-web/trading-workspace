"""
DlqConsumer — lee streams *.dead_letter del AgentMessageBus y persiste en trades.rejected_dlq.

Cuando AgentMessageBus no puede procesar un mensaje después de max_retries,
lo escribe al stream '<channel>.dead_letter'. Este consumer lee esos streams
y los persiste en la DB para revisión humana.

No usa consumer groups (usa XREAD sin grupo) para no necesitar ACKs — es una
lectura de auditoría, no de procesamiento.
"""
from __future__ import annotations

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

# Streams DLQ a monitorear
_DLQ_STREAMS = [
    "agent.proposals.dead_letter",
    "agent.critiques.dead_letter",
    "agent.decisions.dead_letter",
    "agent.atlas_validations.dead_letter",
    "agent.executions.dead_letter",
]

BLOCK_MS = 2_000
BATCH_SIZE = 20


class DlqConsumer:
    """
    Lee los streams DLQ de Redis y persiste entradas en trades.rejected_dlq.

    No tiene consumer groups — usa XREAD con last_id para leer nuevas entradas.
    Safe to run multiple instances (each will process the same entries, idempotent
    porque ON CONFLICT DO NOTHING podría agregarse, pero para el volumen esperado
    no es necesario).
    """

    def __init__(self, redis_client, repo) -> None:
        self._redis = redis_client
        self._repo = repo
        self._running = False
        self._thread: threading.Thread | None = None
        # Per-stream last-seen entry ID (start from $ = only new entries)
        self._last_ids: dict[str, str] = {s: "$" for s in _DLQ_STREAMS}

    @classmethod
    def from_env(cls, repo) -> "DlqConsumer":
        import redis
        from multi_agent.config import settings
        return cls(redis.from_url(settings.REDIS_URL, decode_responses=False), repo)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="DlqConsumer"
        )
        self._thread.start()
        logger.info("DlqConsumer started — monitoring %d DLQ streams", len(_DLQ_STREAMS))

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("DlqConsumer stopped")

    def _loop(self) -> None:
        while self._running:
            try:
                self._poll_once()
            except Exception:
                logger.exception("DlqConsumer poll error")

    def _poll_once(self) -> None:
        streams = {s: self._last_ids[s] for s in _DLQ_STREAMS}
        try:
            results = self._redis.xread(streams, count=BATCH_SIZE, block=BLOCK_MS)
        except Exception:
            logger.exception("DlqConsumer xread error")
            return

        if not results:
            return

        for stream_name_raw, entries in results:
            stream_name = (
                stream_name_raw.decode()
                if isinstance(stream_name_raw, bytes)
                else stream_name_raw
            )
            for entry_id, fields in entries:
                entry_id_str = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                self._process_entry(stream_name, entry_id_str, fields)
                self._last_ids[stream_name] = entry_id_str

    def _process_entry(self, stream: str, entry_id: str, fields: dict) -> None:
        def _decode(v):
            return v.decode() if isinstance(v, bytes) else v

        reason_raw = _decode(fields.get(b"reason") or fields.get("reason", "unknown"))
        payload_raw = _decode(fields.get(b"payload") or fields.get("payload", "{}"))
        original_channel = _decode(
            fields.get(b"original_channel") or fields.get("original_channel", stream)
        )

        try:
            payload = json.loads(payload_raw)
        except Exception:
            payload = {"raw": payload_raw}

        # Try to extract identifiers from payload
        correlation_id = payload.get("correlation_id")
        proposing_agent = payload.get("agent_id")

        # Try to extract ticker from nested proposal structure
        ticker = None
        if "trade" in payload:
            ticker = payload["trade"].get("ticker")

        try:
            self._repo.save_rejected_dlq(
                source="bus_dlq",
                correlation_id=correlation_id,
                ticker=ticker,
                proposing_agent=proposing_agent,
                reason=f"bus_dlq:{reason_raw}",
                original_channel=original_channel,
                dlq_entry_id=entry_id,
                payload=payload,
                atlas_version=None,
            )
            logger.warning(
                "DLQ entry persisted: stream=%s entry=%s reason=%s",
                stream,
                entry_id,
                reason_raw,
            )
        except Exception:
            logger.exception(
                "Failed to persist DLQ entry stream=%s entry=%s", stream, entry_id
            )
