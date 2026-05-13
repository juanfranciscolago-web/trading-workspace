"""
SchwabDataLayer — real broker-backed MarketState for Sprint 5+.

Wraps SchwabClient (auth + get_price_history + get_options_chain) and maps
Schwab's responses to the DataLayer / MarketState shape that ATHENA consumes.

Sprint 5 caveats (per ADR-004):
    - iv_rank / iv_percentile are placeholders (default 50.0). Real percentile
      vs trailing 252 days lands Sprint 6+ via iv_history table (ADR-005).
    - ohlcv_hourly is intentionally empty (D-η: hourly resample deferred to
      Sprint 6+ when HERMES tactical lands).
    - skew uses 25-delta strikes (ADR-004 D5), NOT 1σ moves despite
      SkewSnapshot field naming inherited from StubDataLayer.

One snapshot() call issues ~12 Schwab API calls (6 tickers × {price_history,
options_chain}). Total wall-clock ~3-6s at typical Schwab latency.
SchwabAPIError propagates — ATHENA cannot proceed without data.
"""
from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timezone

from .interfaces import DataLayer, MarketState, OHLCV, SkewSnapshot, TickerSnapshot
from .universe import TICKER_UNIVERSE

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

TARGET_DTE_DAYS = 30                # Skew computed at expiration ~30 days out
DTE_PROXIMITY_DAYS = 15             # Accept 30 ± 15 days (matches ATHENA 15-45)
DELTA_TARGET = 0.25                 # 25-delta skew (ADR-004 D5, industry std)
DELTA_PROXIMITY_WARN = 0.10         # Logs warning if closest delta diff > this
DAILY_HISTORY_PERIOD_MONTHS = 3     # ~63 trading days — enough for 30d realized vol


# ── SchwabDataLayer ───────────────────────────────────────────────────────────

class SchwabDataLayer(DataLayer):
    """Broker-backed DataLayer for Sprint 5+.

    Each snapshot() call fetches daily OHLCV + options chain for all 6 tickers
    in TICKER_UNIVERSE, builds TickerSnapshots, computes pairwise correlations
    from log returns, and returns a MarketState.

    iv_rank / iv_percentile are placeholders (default 50.0) until iv_history
    table lands Sprint 6+.
    """

    def __init__(
        self,
        schwab_client,  # SchwabClient (duck-typed to keep tests mock-friendly)
        *,
        iv_rank_default: float = 50.0,
        iv_percentile_default: float = 50.0,
    ) -> None:
        self._client = schwab_client
        self._iv_rank_default = iv_rank_default
        self._iv_percentile_default = iv_percentile_default

    # ── Public API ────────────────────────────────────────────────────────────

    def snapshot(self) -> MarketState:
        """Fetch full universe state from Schwab and return a MarketState.

        Issues 12 Schwab API calls (6 tickers × 2 endpoints). Any
        SchwabAPIError propagates — ATHENA cannot operate on degraded data.
        """
        now = datetime.now(timezone.utc)

        # 1. Fetch daily OHLCV + chain per ticker.
        daily_by_ticker: dict[str, list[OHLCV]] = {}
        chain_by_ticker: dict[str, dict] = {}
        for ticker in TICKER_UNIVERSE.keys():
            daily_by_ticker[ticker] = self._fetch_daily_ohlcv(ticker)
            chain_by_ticker[ticker] = self._client.get_options_chain(ticker)

        # 2. Build TickerSnapshots.
        tickers: dict[str, TickerSnapshot] = {}
        for ticker in TICKER_UNIVERSE.keys():
            tickers[ticker] = self._build_ticker_snapshot(
                ticker,
                daily_by_ticker[ticker],
                chain_by_ticker[ticker],
            )

        # 3. Pairwise correlations.
        correlations = self._compute_correlations(daily_by_ticker)

        return MarketState(
            timestamp=now,
            tickers=tickers,
            correlations=correlations,
        )

    # ── Per-ticker build ──────────────────────────────────────────────────────

    def _build_ticker_snapshot(
        self,
        ticker: str,
        daily_candles: list[OHLCV],
        chain: dict,
    ) -> TickerSnapshot:
        if not daily_candles:
            raise ValueError(
                f"No daily candles for {ticker} — Schwab returned empty"
            )

        last_price = daily_candles[-1].close
        realized_vol_30d = self._compute_realized_vol(daily_candles[-30:])
        skew = self._build_skew_from_chain(chain, last_price)

        return TickerSnapshot(
            ticker=ticker,
            last_price=round(last_price, 2),
            ohlcv_daily=daily_candles,
            ohlcv_hourly=[],                                # D-η deferred
            iv_rank=self._iv_rank_default,
            iv_percentile=self._iv_percentile_default,
            skew=skew,
            realized_vol_30d=round(realized_vol_30d, 4),
        )

    # ── Schwab fetch helpers ──────────────────────────────────────────────────

    def _fetch_daily_ohlcv(self, ticker: str) -> list[OHLCV]:
        """Fetch daily candles for a ticker via SchwabClient."""
        candles = self._client.get_price_history(
            symbol=ticker,
            period_type="month",
            period=DAILY_HISTORY_PERIOD_MONTHS,
            frequency_type="daily",
            frequency=1,
        )
        return [self._schwab_candle_to_ohlcv(c) for c in candles]

    @staticmethod
    def _schwab_candle_to_ohlcv(candle: dict) -> OHLCV:
        """Convert Schwab's raw candle dict to OHLCV.

        Schwab `datetime` field is epoch milliseconds. OHLCV.timestamp is
        tz-aware UTC.
        """
        return OHLCV(
            timestamp=datetime.fromtimestamp(
                candle["datetime"] / 1000.0, tz=timezone.utc
            ),
            open=candle["open"],
            high=candle["high"],
            low=candle["low"],
            close=candle["close"],
            volume=candle["volume"],
        )

    # ── Skew computation ──────────────────────────────────────────────────────

    def _build_skew_from_chain(
        self,
        chain: dict,
        spot_price: float,
    ) -> SkewSnapshot:
        """Build SkewSnapshot from a normalized chain dict.

        ATM IV: call IV at the strike closest to spot.
        Put skew IV: put IV at the contract with delta closest to -0.25.
        Call skew IV: call IV at the contract with delta closest to +0.25.

        All from one expiration ~TARGET_DTE_DAYS out. If no expiration falls
        within DTE_PROXIMITY_DAYS of the target, returns zeros + warning.
        """
        target_exp = self._find_target_expiration(chain)
        if target_exp is None:
            logger.warning(
                "No expiration for %s within %d ± %d DTE — skew=0",
                chain.get("underlying", "?"),
                TARGET_DTE_DAYS, DTE_PROXIMITY_DAYS,
            )
            return SkewSnapshot(atm_iv=0.0, put_skew_iv=0.0, call_skew_iv=0.0)

        call_strikes = chain.get("calls", {}).get(target_exp, {})
        put_strikes = chain.get("puts", {}).get(target_exp, {})

        # ATM IV: call IV at strike closest to spot price.
        atm_strike = self._find_atm_strike(call_strikes, spot_price)
        atm_iv = call_strikes[atm_strike]["iv"] if atm_strike else 0.0

        # 25-delta call + put.
        call_25d = self._find_delta_contract(call_strikes, target_delta=DELTA_TARGET)
        put_25d  = self._find_delta_contract(put_strikes, target_delta=-DELTA_TARGET)

        return SkewSnapshot(
            atm_iv=round(atm_iv, 4),
            put_skew_iv=round(put_25d["iv"] if put_25d else 0.0, 4),
            call_skew_iv=round(call_25d["iv"] if call_25d else 0.0, 4),
        )

    @staticmethod
    def _find_target_expiration(chain: dict) -> str | None:
        """Find expiration in chain whose DTE is closest to TARGET_DTE_DAYS.

        Returns None if no expiration's DTE falls within
        TARGET_DTE_DAYS ± DTE_PROXIMITY_DAYS.
        """
        expirations = chain.get("expirations", [])
        calls = chain.get("calls", {})

        best_exp = None
        best_diff = None
        for exp in expirations:
            strikes = calls.get(exp, {})
            if not strikes:
                continue
            # dte is the same for all strikes in this expiration.
            any_contract = next(iter(strikes.values()))
            dte = any_contract.get("dte", -1)
            diff = abs(dte - TARGET_DTE_DAYS)
            if diff > DTE_PROXIMITY_DAYS:
                continue
            if best_diff is None or diff < best_diff:
                best_exp = exp
                best_diff = diff
        return best_exp

    @staticmethod
    def _find_atm_strike(strikes_dict: dict, spot_price: float) -> str | None:
        """Return strike_str closest to spot_price. None if empty."""
        if not strikes_dict:
            return None
        return min(strikes_dict.keys(), key=lambda s: abs(float(s) - spot_price))

    @staticmethod
    def _find_delta_contract(
        strikes_dict: dict,
        *,
        target_delta: float,
    ) -> dict | None:
        """Find contract with delta closest to target_delta.

        Always returns the closest match (never None unless strikes_dict is
        empty). Logs warning if proximity exceeds DELTA_PROXIMITY_WARN —
        signals strikes spacing is too wide for clean 25-delta lookup.
        """
        if not strikes_dict:
            return None
        best_contract = None
        best_diff = None
        for contract in strikes_dict.values():
            delta = contract.get("delta", 0.0)
            diff = abs(delta - target_delta)
            if best_diff is None or diff < best_diff:
                best_contract = contract
                best_diff = diff
        if best_contract is not None and best_diff > DELTA_PROXIMITY_WARN:
            logger.warning(
                "Loose %.2f-delta match: closest delta=%.3f (diff=%.3f > %.2f)",
                target_delta, best_contract.get("delta", 0.0),
                best_diff, DELTA_PROXIMITY_WARN,
            )
        return best_contract

    # ── Realized vol ──────────────────────────────────────────────────────────

    @staticmethod
    def _compute_realized_vol(bars: list[OHLCV]) -> float:
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

    # ── Correlations ──────────────────────────────────────────────────────────

    @staticmethod
    def _compute_correlations(
        daily_by_ticker: dict[str, list[OHLCV]],
    ) -> dict[tuple[str, str], float]:
        """Pairwise Pearson correlation of daily log returns across tickers.

        Returns {(a, b): rho} with a < b alphabetically. Each pair appears
        once. Assumes daily bars are aligned by trading day (true for NYSE
        common universe). Falls back to 0.0 on mismatched series lengths.
        """
        returns_by_ticker: dict[str, list[float]] = {}
        for ticker, bars in daily_by_ticker.items():
            if len(bars) < 2:
                returns_by_ticker[ticker] = []
                continue
            returns_by_ticker[ticker] = [
                math.log(bars[i].close / bars[i - 1].close)
                for i in range(1, len(bars))
            ]

        result: dict[tuple[str, str], float] = {}
        tickers = sorted(returns_by_ticker.keys())
        for i, a in enumerate(tickers):
            for b in tickers[i + 1:]:
                xs = returns_by_ticker[a]
                ys = returns_by_ticker[b]
                if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
                    result[(a, b)] = 0.0
                    continue
                try:
                    rho = statistics.correlation(xs, ys)
                except statistics.StatisticsError:
                    rho = 0.0
                result[(a, b)] = round(rho, 3)
        return result
