"""
StubDataLayer — synthetic seeded MarketState for Sprint 3 dev and testing.

Generates plausible OHLCV / IV / skew / correlations using `random.Random(seed)`
so the same seed produces identical data fields. The top-level MarketState
timestamp uses `datetime.now()` (wall-clock) and is excluded from determinism
guarantees — tests that assert determinism compare per-ticker fields, not the
top-level timestamp.

Sprint 5 will replace this with SchwabDataLayer hitting the real broker API.
Both implement the same DataLayer interface from `interfaces.py`.
"""
from __future__ import annotations

import math
import random
import statistics
from datetime import datetime, timedelta, timezone

from .interfaces import DataLayer, MarketState, OHLCV, SkewSnapshot, TickerSnapshot
from .universe import TICKER_UNIVERSE, TickerProfile


# ── Module constants ──────────────────────────────────────────────────────────

# Plausible pairwise correlations. Keys are (a, b) with a < b alphabetically.
# Rationale: SPY-QQQ very high (broad indices), SPY-IWM medium (large-cap vs
# small-cap), tech mega-caps moderately correlated to each other, IWM relatively
# uncorrelated with tech mega-caps.
#
# Note: these values are reported as PRE-COMPUTED metadata (as a real system
# would receive from a market data vendor or its own analytics layer), NOT
# the empirical correlation of the random-walk OHLCVs in this stub. The stub
# generates each ticker's path with an independent random stream, so empirical
# correlation of the synthesized 60-day returns is ~0. ATHENA consumes the
# `correlations` field directly without recomputing — same flow as production
# would be (consumer reads pre-computed correlations, doesn't recalculate).
# If a future test or feature needs *consistent* synthetic returns matching
# these correlations, generate them via Cholesky decomposition then.
_CORRELATION_BASELINE: dict[tuple[str, str], float] = {
    ("AAPL", "IWM"):  0.40,
    ("AAPL", "MSFT"): 0.65,
    ("AAPL", "NVDA"): 0.55,
    ("AAPL", "QQQ"):  0.75,
    ("AAPL", "SPY"):  0.65,
    ("IWM",  "MSFT"): 0.42,
    ("IWM",  "NVDA"): 0.35,
    ("IWM",  "QQQ"):  0.65,
    ("IWM",  "SPY"):  0.75,
    ("MSFT", "NVDA"): 0.60,
    ("MSFT", "QQQ"):  0.78,
    ("MSFT", "SPY"):  0.70,
    ("NVDA", "QQQ"):  0.72,
    ("NVDA", "SPY"):  0.55,
    ("QQQ",  "SPY"):  0.90,
}

# Baseline daily volume; per-bar volume is jittered around this.
_BASE_VOLUME = 50_000_000


# ── StubDataLayer ─────────────────────────────────────────────────────────────

class StubDataLayer(DataLayer):
    """Synthetic seeded data layer for Sprint 3 dev and testing.

    Same seed → same MarketState (except top-level wall-clock timestamp).
    Tests use a fixed seed and compare per-ticker fields field-by-field.
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed

    def snapshot(self) -> MarketState:
        rng = random.Random(self._seed)
        now = datetime.now(timezone.utc)

        tickers: dict[str, TickerSnapshot] = {}
        for ticker, profile in TICKER_UNIVERSE.items():
            tickers[ticker] = self._build_ticker_snapshot(profile, rng, now)

        correlations = self._build_correlations(rng)

        return MarketState(
            timestamp=now,
            tickers=tickers,
            correlations=correlations,
        )

    # ── Per-ticker generation ────────────────────────────────────────────────

    def _build_ticker_snapshot(
        self,
        profile: TickerProfile,
        rng: random.Random,
        now: datetime,
    ) -> TickerSnapshot:
        ohlcv_daily = self._generate_ohlcv_daily(profile, rng, now)
        ohlcv_hourly = self._generate_ohlcv_hourly(ohlcv_daily[-1], profile, rng, now)

        last_price = ohlcv_daily[-1].close
        realized_vol_30d = self._compute_realized_vol(ohlcv_daily[-30:])
        iv_rank = max(0.0, min(100.0, profile.iv_rank_bias + rng.uniform(-10.0, 10.0)))
        iv_percentile = max(0.0, min(100.0, iv_rank + rng.uniform(-5.0, 5.0)))
        skew = self._build_skew(realized_vol_30d, iv_rank, rng)

        return TickerSnapshot(
            ticker=profile.ticker,
            last_price=round(last_price, 2),
            ohlcv_daily=ohlcv_daily,
            ohlcv_hourly=ohlcv_hourly,
            iv_rank=round(iv_rank, 1),
            iv_percentile=round(iv_percentile, 1),
            skew=skew,
            realized_vol_30d=round(realized_vol_30d, 4),
        )

    def _generate_ohlcv_daily(
        self,
        profile: TickerProfile,
        rng: random.Random,
        now: datetime,
    ) -> list[OHLCV]:
        """Generate 60 daily bars via geometric Brownian motion."""
        bars: list[OHLCV] = []
        daily_drift = profile.drift / 252
        daily_vol = profile.annualized_vol / math.sqrt(252)
        price = profile.base_price
        # Bars dated 60 days ago to today, market close (21:00 UTC ~ 16:00 ET).
        end_date = now.replace(hour=21, minute=0, second=0, microsecond=0)
        for i in range(60):
            bar_date = end_date - timedelta(days=60 - 1 - i)
            z = rng.gauss(0.0, 1.0)
            log_return = daily_drift + daily_vol * z
            new_close = price * math.exp(log_return)
            open_price = price
            high = max(open_price, new_close) * (1.0 + abs(rng.gauss(0.0, 0.003)))
            low = min(open_price, new_close) * (1.0 - abs(rng.gauss(0.0, 0.003)))
            volume = int(_BASE_VOLUME * (0.5 + rng.random()))
            bars.append(OHLCV(
                timestamp=bar_date,
                open=round(open_price, 2),
                high=round(high, 2),
                low=round(low, 2),
                close=round(new_close, 2),
                volume=volume,
            ))
            price = new_close
        return bars

    def _generate_ohlcv_hourly(
        self,
        last_daily: OHLCV,
        profile: TickerProfile,
        rng: random.Random,
        now: datetime,
    ) -> list[OHLCV]:
        """Generate 24 hourly bars from last_daily.open to last_daily.close."""
        bars: list[OHLCV] = []
        hourly_vol = profile.annualized_vol / math.sqrt(252 * 24)
        # Drift compensates so the expected final close matches last_daily.close.
        hourly_drift = math.log(last_daily.close / last_daily.open) / 24
        price = last_daily.open
        end_time = now.replace(minute=0, second=0, microsecond=0)
        for i in range(24):
            bar_time = end_time - timedelta(hours=24 - 1 - i)
            z = rng.gauss(0.0, 1.0)
            log_return = hourly_drift + hourly_vol * z
            new_close = price * math.exp(log_return)
            open_price = price
            high = max(open_price, new_close) * (1.0 + abs(rng.gauss(0.0, 0.001)))
            low = min(open_price, new_close) * (1.0 - abs(rng.gauss(0.0, 0.001)))
            volume = int(_BASE_VOLUME * 0.04 * (0.5 + rng.random()))
            bars.append(OHLCV(
                timestamp=bar_time,
                open=round(open_price, 2),
                high=round(high, 2),
                low=round(low, 2),
                close=round(new_close, 2),
                volume=volume,
            ))
            price = new_close
        return bars

    def _compute_realized_vol(self, bars: list[OHLCV]) -> float:
        """Annualized realized vol from daily close-to-close log returns."""
        if len(bars) < 2:
            return 0.0
        log_returns = [
            math.log(bars[i].close / bars[i - 1].close)
            for i in range(1, len(bars))
        ]
        if len(log_returns) < 2:
            return 0.0
        sigma_daily = statistics.stdev(log_returns)
        return sigma_daily * math.sqrt(252)

    def _build_skew(
        self,
        realized_vol_30d: float,
        iv_rank: float,
        rng: random.Random,
    ) -> SkewSnapshot:
        """Skew with put bias (puts pricier than calls)."""
        # ATM IV scales above realized vol when IV rank is elevated.
        # iv_rank=0 → atm_iv ≈ realized; iv_rank=100 → atm_iv ≈ realized * 1.5.
        atm_iv = realized_vol_30d * (1.0 + iv_rank / 100.0 * 0.5)
        put_skew_iv = atm_iv * rng.uniform(1.05, 1.15)
        call_skew_iv = atm_iv * rng.uniform(0.92, 1.02)
        return SkewSnapshot(
            atm_iv=round(atm_iv, 4),
            put_skew_iv=round(put_skew_iv, 4),
            call_skew_iv=round(call_skew_iv, 4),
        )

    # ── Correlations ─────────────────────────────────────────────────────────

    def _build_correlations(
        self,
        rng: random.Random,
    ) -> dict[tuple[str, str], float]:
        """Apply small jitter (±0.05) to the baseline correlation matrix."""
        result: dict[tuple[str, str], float] = {}
        for pair, base in _CORRELATION_BASELINE.items():
            jittered = base + rng.uniform(-0.05, 0.05)
            jittered = max(-1.0, min(1.0, jittered))
            result[pair] = round(jittered, 3)
        return result
