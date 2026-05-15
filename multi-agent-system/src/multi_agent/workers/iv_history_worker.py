"""IvHistoryWorker — nightly ATM IV snapshot worker (S.6.iv-c).

Matches RetryWorker pattern: asyncio.Event-based shutdown, predicate-driven
poll loop. Snapshots all TICKER_UNIVERSE at 21:15 UTC daily, calls
IvHistoryRepository.write_snapshot for each ticker with valid ATM IV.

ADR-005 references:
- D3: ATM IV = avg(call.iv, put.iv) at strike closest to spot.
      (Compute logic lives en `multi_agent.data_layer.iv_compute` —
       single source of truth shared with SchwabDataLayer per S.6.iv-d.)
- D4: 21:15 UTC daily timing.
- D7: Custom asyncio worker (NO APScheduler).
- D10: Weekend skip via datetime.weekday(); holiday detection via Schwab
  empty chain → log warning + skip.
- D-γ: Per-ticker error isolation (1 ticker fail does NOT crash worker).
- D-θ: Predicate-based should_snapshot_now (idempotent via DB ON CONFLICT).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from multi_agent.data_layer.universe import TICKER_UNIVERSE
from multi_agent.data_layer.iv_compute import compute_atm_iv
from multi_agent.persistence.iv_history_repository import IvHistoryRepository
from shared_core.brokers.schwab_client import SchwabClient

logger = logging.getLogger(__name__)


class IvHistoryWorker:
    """Nightly ATM IV snapshot worker for iv_rank computation.

    Polls every poll_interval_s (default 60s). When predicate is true
    (post-21:15 UTC, weekday, no snapshot today for SPY canary), runs
    snapshot_all_tickers() which iterates TICKER_UNIVERSE and writes
    ATM IV per ticker via IvHistoryRepository.
    """

    SNAPSHOT_HOUR_UTC = 21
    SNAPSHOT_MINUTE_UTC = 15
    POLL_INTERVAL_S = 60.0
    CANARY_TICKER = "SPY"  # Used for has_snapshot_today predicate

    def __init__(
        self,
        repo: IvHistoryRepository,
        schwab_client: SchwabClient,
        poll_interval_s: float | None = None,
    ) -> None:
        self._repo = repo
        self._client = schwab_client
        self._poll_interval = poll_interval_s or self.POLL_INTERVAL_S
        self._stop_event = asyncio.Event()

    def shutdown(self) -> None:
        """Signal worker to stop on next loop iteration."""
        self._stop_event.set()

    async def run(self) -> None:
        """Main worker loop. Polls predicate every poll_interval_s."""
        self._stop_event.clear()
        logger.info(
            "IvHistoryWorker started (snapshot at %02d:%02d UTC daily)",
            self.SNAPSHOT_HOUR_UTC, self.SNAPSHOT_MINUTE_UTC,
        )
        while not self._stop_event.is_set():
            try:
                if self._should_snapshot_now():
                    await self._snapshot_all_tickers()
            except Exception:
                # Worker-level exception isolation — log + continue loop.
                # Individual ticker failures handled in _snapshot_all_tickers.
                logger.exception("IvHistoryWorker iteration failed unexpectedly")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval,
                )
            except asyncio.TimeoutError:
                continue  # Normal poll interval elapsed.
            else:
                break  # Shutdown during sleep.

        logger.info("IvHistoryWorker stopped")

    def _should_snapshot_now(self) -> bool:
        """Predicate: returns True iff snapshot should run NOW.

        Conditions (all must be True):
        1. Today is a weekday (Monday-Friday in UTC).
        2. Current UTC time is past today's SNAPSHOT_HOUR:MINUTE.
        3. No iv_history row for CANARY_TICKER today (D-θ canary check).
        """
        now = datetime.now(timezone.utc)

        # 1. Weekend skip (D10).
        if now.weekday() in (5, 6):  # Saturday=5, Sunday=6
            return False

        # 2. Time gate.
        snapshot_time_today = now.replace(
            hour=self.SNAPSHOT_HOUR_UTC,
            minute=self.SNAPSHOT_MINUTE_UTC,
            second=0,
            microsecond=0,
        )
        if now < snapshot_time_today:
            return False

        # 3. Canary check: avoid re-snapshot same day.
        if self._repo.has_snapshot_today(self.CANARY_TICKER, now.date()):
            return False

        return True

    async def _snapshot_all_tickers(self) -> None:
        """Fetch + persist ATM IV for all TICKER_UNIVERSE tickers.

        Per D-γ: per-ticker error isolation. If one ticker fails, log
        warning and continue with others. Uses fixed ts at 21:15:00 UTC
        sharp (Q4) for idempotency.
        """
        snapshot_ts = self._compute_snapshot_ts()
        logger.info("Starting IV snapshot run for ts=%s", snapshot_ts.isoformat())

        success_count = 0
        for ticker in TICKER_UNIVERSE.keys():
            try:
                self._snapshot_one_ticker(ticker, snapshot_ts)
                success_count += 1
            except Exception:
                # Per-ticker isolation (D-γ).
                logger.exception("Snapshot failed for ticker=%s, skipping", ticker)

        total = len(TICKER_UNIVERSE)
        if success_count == 0:
            logger.error("IV snapshot run completed: 0/%d tickers succeeded", total)
        elif success_count < total:
            logger.warning(
                "IV snapshot run completed: %d/%d tickers succeeded",
                success_count, total,
            )
        else:
            logger.info("IV snapshot run completed: %d/%d tickers ok", success_count, total)

    def _snapshot_one_ticker(self, ticker: str, snapshot_ts: datetime) -> None:
        """Fetch chain, compute ATM IV per D3, persist."""
        chain = self._client.get_options_chain(ticker)

        # D10: empty chain → holiday detection. Skip ticker.
        if not chain or not chain.get("expirations"):
            logger.warning(
                "Empty chain for %s — possibly holiday or market closed. Skipping.",
                ticker,
            )
            return

        spot = chain.get("spot", {}).get("last", 0.0)
        atm_iv = compute_atm_iv(chain, spot)

        if atm_iv is None:
            logger.warning("Could not compute ATM IV for %s (both call/put missing)", ticker)
            return

        self._repo.write_snapshot(
            ticker=ticker,
            ts=snapshot_ts,
            atm_iv=atm_iv,
            underlying_close=spot if spot > 0 else None,
        )

    def _compute_snapshot_ts(self) -> datetime:
        """Fixed ts at 21:15:00 UTC sharp today (Q4 idempotency)."""
        now = datetime.now(timezone.utc)
        return now.replace(
            hour=self.SNAPSHOT_HOUR_UTC,
            minute=self.SNAPSHOT_MINUTE_UTC,
            second=0,
            microsecond=0,
        )
