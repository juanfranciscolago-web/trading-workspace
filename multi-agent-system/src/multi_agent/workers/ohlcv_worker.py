"""OhlcvWorker — daily 21:30 UTC OHLCV snapshot Tier C foundation (S.9.ohl-b).

Schedule: every weekday 21:30 UTC (D3 stagger from IvHistoryWorker 21:15 UTC,
F-r7 mitigation).

Cadence: each fire iterates TICKER_UNIVERSE × TIMEFRAMES = 6 × 4 = 24 cells.
Each cell fetches Schwab REST get_price_history(period_type="day", period=10)
+ writes idempotent via Repository.write_bars (ON CONFLICT DO NOTHING).

D6 (KISS): NO bootstrap-vs-incremental branching. Each run pulls 10-day window
uniformly. Overlap safe via PK (ts, ticker, timeframe).

D-γ isolation per (ticker, timeframe) cell — inner exception → WARNING + continue.

Canary D-θ analog: max_ts_for_ticker("SPY", "1d") >= today_21_30_utc → skip
this run (already populated).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multi_agent.persistence.ohlcv_repository import OhlcvRepository
    from shared_core.brokers.schwab_client import SchwabClient

from multi_agent.data_layer.universe import TICKER_UNIVERSE

logger = logging.getLogger(__name__)

SNAPSHOT_HOUR_UTC = 21
SNAPSHOT_MINUTE_UTC = 30  # D3 stagger from IvHistoryWorker (21:15 UTC)
POLL_INTERVAL_S = 60.0
CANARY_TICKER = "SPY"
CANARY_TIMEFRAME = "1d"

# D2 Phase 1: 4 timeframes per Schwab native frequency_type+frequency.
TIMEFRAMES: dict[str, dict[str, str | int]] = {
    "5m": {
        "period_type": "day",
        "period": 10,
        "frequency_type": "minute",
        "frequency": 5,
    },
    "15m": {
        "period_type": "day",
        "period": 10,
        "frequency_type": "minute",
        "frequency": 15,
    },
    "30m": {
        "period_type": "day",
        "period": 10,
        "frequency_type": "minute",
        "frequency": 30,
    },
    "1d": {
        "period_type": "day",
        "period": 10,
        "frequency_type": "daily",
        "frequency": 1,
    },
}


class OhlcvWorker:
    """Scheduled OHLCV snapshot worker for Tier C foundation."""

    def __init__(
        self,
        repo: "OhlcvRepository",
        schwab_client: "SchwabClient",
        poll_interval_s: float | None = None,
    ) -> None:
        """Construct worker.

        Args:
            repo: OhlcvRepository instance.
            schwab_client: SchwabClient (own copy per app.py pattern).
            poll_interval_s: Override for tests (default 60.0).
        """
        self._repo = repo
        self._client = schwab_client
        self._poll = poll_interval_s if poll_interval_s is not None else POLL_INTERVAL_S
        self._stop_event = asyncio.Event()

    def shutdown(self) -> None:
        """Signal worker to stop on next poll iteration."""
        self._stop_event.set()

    async def run(self) -> None:
        """Main loop: poll _should_fetch_now() until shutdown."""
        logger.info(
            "OhlcvWorker started: snapshot %02d:%02d UTC daily, %d timeframes",
            SNAPSHOT_HOUR_UTC,
            SNAPSHOT_MINUTE_UTC,
            len(TIMEFRAMES),
        )
        while not self._stop_event.is_set():
            try:
                if self._should_fetch_now():
                    await self._fetch_all_tickers()
            except Exception:  # noqa: BLE001
                logger.exception("OhlcvWorker loop error (continuing)")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll)
            except asyncio.TimeoutError:
                pass

        logger.info("OhlcvWorker stopped")

    def _should_fetch_now(self) -> bool:
        """Predicate: weekday + 21:30 UTC time gate + canary check.

        Canary (D-θ analog): if max_ts for SPY 1d >= today_21_30_utc, skip
        (already populated this run cycle).
        """
        now = datetime.now(timezone.utc)

        # Weekday gate (Mon=0..Fri=4)
        if now.weekday() >= 5:
            return False

        # Time gate: at or past 21:30 UTC
        target_ts = now.replace(
            hour=SNAPSHOT_HOUR_UTC,
            minute=SNAPSHOT_MINUTE_UTC,
            second=0,
            microsecond=0,
        )
        if now < target_ts:
            return False

        # Canary check: skip if already populated this run cycle
        max_ts = self._repo.max_ts_for_ticker(CANARY_TICKER, CANARY_TIMEFRAME)
        if max_ts is not None and max_ts >= target_ts:
            return False

        return True

    async def _fetch_all_tickers(self) -> None:
        """Iterate TICKER_UNIVERSE × TIMEFRAMES with per-cell isolation."""
        tickers = list(TICKER_UNIVERSE.keys())
        total_cells = len(tickers) * len(TIMEFRAMES)
        logger.info(
            "OhlcvWorker: starting fetch run, %d cells (%d tickers × %d timeframes)",
            total_cells,
            len(tickers),
            len(TIMEFRAMES),
        )
        success = 0
        for ticker in tickers:
            for timeframe in TIMEFRAMES:
                try:
                    await asyncio.to_thread(
                        self._fetch_ticker_timeframe, ticker, timeframe
                    )
                    success += 1
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "OhlcvWorker: %s %s fetch failed (D-γ isolation), continuing",
                        ticker,
                        timeframe,
                        exc_info=True,
                    )
        logger.info(
            "OhlcvWorker: fetch run complete, %d/%d cells succeeded",
            success,
            total_cells,
        )

    def _fetch_ticker_timeframe(self, ticker: str, timeframe: str) -> None:
        """Fetch + persist single (ticker, timeframe) cell."""
        params = TIMEFRAMES[timeframe]
        candles = self._client.get_price_history(
            symbol=ticker,
            period_type=params["period_type"],
            period=params["period"],
            frequency_type=params["frequency_type"],
            frequency=params["frequency"],
        )

        bars: list[dict] = []
        for c in candles:
            epoch_ms = c.get("datetime")
            if epoch_ms is None:
                continue
            ts = self._epoch_ms_to_datetime(int(epoch_ms))
            bars.append(
                {
                    "ts": ts,
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c.get("volume"),
                }
            )

        n = self._repo.write_bars(ticker, timeframe, bars)
        logger.debug(
            "OhlcvWorker: %s %s wrote %d bars", ticker, timeframe, n
        )

    @staticmethod
    def _epoch_ms_to_datetime(epoch_ms: int) -> datetime:
        """Convert Schwab epoch_ms to tz-aware UTC datetime (F-r6 pattern)."""
        return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
