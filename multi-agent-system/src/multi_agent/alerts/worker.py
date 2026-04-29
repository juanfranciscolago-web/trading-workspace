"""
AlertWorker — async loop that subscribes to Redis and feeds AlertRouter.

Lifecycle (controlled from FastAPI lifespan via asyncio.create_task):
  start: task = asyncio.create_task(worker.run())
  stop:  worker.shutdown()
         await asyncio.wait_for(task, timeout=10)

Shutdown sequence:
  1. _stop event is set — run() stops accepting new events
  2. In-flight routing calls are awaited with a 5s drain timeout
  3. Redis pub/sub connection is closed by the bus generator's finally block
"""
from __future__ import annotations

import asyncio
import logging

from .bus import AlertBus
from .router import AlertRouter

logger = logging.getLogger(__name__)

_DRAIN_TIMEOUT_S = 5.0


class AlertWorker:

    def __init__(self, bus: AlertBus, router: AlertRouter) -> None:
        self._bus = bus
        self._router = router
        self._stop = asyncio.Event()
        self._in_flight: set[asyncio.Task] = set()

    def shutdown(self) -> None:
        """Signal the worker to stop accepting new events."""
        self._stop.set()
        logger.info("AlertWorker shutdown requested")

    async def run(self) -> None:
        """Main async loop. Exits cleanly when shutdown() is called."""
        logger.info("AlertWorker started")
        try:
            async for event in self._bus.subscribe():
                if self._stop.is_set():
                    break
                if event is None:
                    # Timeout tick from subscribe() — check stop signal
                    continue
                task = asyncio.create_task(self._router.route(event))
                self._in_flight.add(task)
                task.add_done_callback(self._in_flight.discard)
        except asyncio.CancelledError:
            pass
        finally:
            await self._drain()
            logger.info("AlertWorker stopped")

    async def _drain(self) -> None:
        """Wait for all in-flight routing tasks to complete (max 5s)."""
        if not self._in_flight:
            return
        logger.info("AlertWorker draining %d in-flight tasks", len(self._in_flight))
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._in_flight, return_exceptions=True),
                timeout=_DRAIN_TIMEOUT_S,
            )
            logger.info("AlertWorker drain complete")
        except asyncio.TimeoutError:
            logger.warning(
                "AlertWorker drain timed out after %.1fs — %d tasks abandoned",
                _DRAIN_TIMEOUT_S, len(self._in_flight),
            )
