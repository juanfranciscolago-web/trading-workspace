"""
SchwabDataLayer — real broker-backed MarketState for Sprint 5+.

Wraps SchwabClient (auth + get_price_history + get_options_chain) and maps
Schwab's responses to the DataLayer / MarketState shape that ATHENA consumes.

Sprint 5/6 caveats (per ADR-004 + ADR-005):
    - iv_rank / iv_percentile: computed per ADR-005 D5 progressive disclosure
      from iv_history table (S.6.iv-d). Fallback to 50.0 when iv_history_repo
      is None (testing) or N<10 days history (bootstrap phase). Per D6,
      iv_percentile = iv_rank in Phase 1 (same value, semantic reserve).
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
from typing import TYPE_CHECKING

from shared_core.brokers.schwab_client import SchwabClient
from shared_core.utils.indicators import iv_rank as _shared_iv_rank

from .interfaces import DataLayer, MarketState, OHLCV, SkewSnapshot, TickerSnapshot
from .iv_compute import compute_atm_iv
from .universe import TICKER_UNIVERSE

if TYPE_CHECKING:
    from ..persistence.iv_history_repository import IvHistoryRepository

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

    iv_rank / iv_percentile: computed per ADR-005 D5 progressive disclosure
    when iv_history_repo is provided. Falls back to 50.0 when None (testing)
    or N<10 historical samples (bootstrap, per D5). D6: iv_percentile mirrors
    iv_rank in Phase 1.
    """

    def __init__(
        self,
        schwab_client: SchwabClient,
        iv_history_repo: IvHistoryRepository | None = None,
    ) -> None:
        """Init SchwabDataLayer.

        Args:
            schwab_client: SchwabClient instance. Duck-typed at runtime;
                MagicMock passes through (annotations not enforced).
            iv_history_repo: Optional IvHistoryRepository for real iv_rank
                compute (S.6.iv-d). If None, iv_rank/iv_percentile fall back
                to 50.0 placeholder per ADR-005 D5 N<10 semantics. Wired by
                lifespan when USE_SCHWAB_DATA_LAYER=True. NOT required to
                preserve testability of existing 22 SchwabDataLayer tests.
        """
        self._client = schwab_client
        self._iv_history_repo = iv_history_repo

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

        # iv_rank/iv_percentile per ADR-005 D5 + D6 (S.6.iv-d).
        current_atm_iv = compute_atm_iv(chain, last_price)
        if current_atm_iv is None:
            # No valid ATM IV in today's chain → cannot compute iv_rank.
            # Distinct from N<10 case: this is "today's data unavailable",
            # that one is "history insufficient".
            logger.debug(
                "iv_rank fallback to 50.0 (no current ATM IV from chain)",
                extra={"ticker": ticker},
            )
            iv_rank_value = 50.0
        else:
            iv_rank_value = self._compute_iv_rank_progressive(
                ticker, current_atm_iv,
            )

        return TickerSnapshot(
            ticker=ticker,
            last_price=round(last_price, 2),
            ohlcv_daily=daily_candles,
            ohlcv_hourly=[],                                # D-η deferred
            iv_rank=iv_rank_value,
            iv_percentile=iv_rank_value,                    # D6: mirror Phase 1
            skew=skew,
            realized_vol_30d=round(realized_vol_30d, 4),
        )

    # ── iv_rank compute (ADR-005 S.6.iv-d) ────────────────────────────────────

    def _compute_iv_rank_progressive(
        self,
        ticker: str,
        current_iv: float,
    ) -> float:
        """Compute iv_rank with D5 progressive disclosure (ADR-005 S.6.iv-d).

        Thresholds (per ADR-005 D5):
            iv_history_repo is None or N < 10  → 50.0  (DEBUG)
            10 <= N < 30                       → percentile  (WARNING)
            30 <= N < 252                      → percentile  (INFO)
            N >= 252                           → percentile  (DEBUG)

        Uses shared_core.utils.indicators.iv_rank (min/max formula) as the
        canonical percentile; thin D5 logic wraps it for log-level routing
        and N<10 hardcoded fallback.

        Args:
            ticker: Ticker for log context.
            current_iv: Today's ATM IV (from compute_atm_iv on current chain).

        Returns:
            iv_rank value in [0, 100]. 50.0 fallback when insufficient
            history or no iv_history_repo wired.
        """
        if self._iv_history_repo is None:
            # Fallback path — fresh deploy without iv_history wired (tests,
            # or USE_SCHWAB_DATA_LAYER=True but iv_history feature off).
            logger.debug(
                "iv_rank fallback to 50.0 (no iv_history_repo)",
                extra={"ticker": ticker},
            )
            return 50.0

        history = self._iv_history_repo.get_history(ticker, days=252)
        n = len(history)

        if n < 10:
            # Bootstrap phase — expected during initial ~10-day accumulation.
            logger.debug(
                "iv_rank bootstrap (N<10), returning 50.0 placeholder",
                extra={"ticker": ticker, "n_samples": n},
            )
            return 50.0

        rank = _shared_iv_rank(current_iv, history)

        if n < 30:
            logger.warning(
                "iv_rank computed on N=%d days only (target 252)",
                n, extra={"ticker": ticker, "n_samples": n, "iv_rank": rank},
            )
        elif n < 252:
            logger.info(
                "iv_rank computed on N=%d days (target 252)",
                n, extra={"ticker": ticker, "n_samples": n, "iv_rank": rank},
            )
        else:
            logger.debug(
                "iv_rank computed on full N=%d days",
                n, extra={"ticker": ticker, "n_samples": n, "iv_rank": rank},
            )

        return rank

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
