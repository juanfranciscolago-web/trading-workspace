"""
DataLayer interface + market state dataclasses.

The DataLayer ABC is the contract real agents use to query market data.
Sprint 3 only has StubDataLayer (synthetic seeded data). Sprint 5 will add
SchwabDataLayer that hits the real broker API — both implement the same
interface.

MarketState is a point-in-time snapshot containing the full universe of
tickers with their OHLCV history, IV state, and pairwise correlations.
ATHENA serializes MarketState to JSON via `to_dict()` and embeds it in the
LLM user prompt.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime


# ── Data points ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OHLCV:
    """Single OHLCV bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class SkewSnapshot:
    """Volatility skew at three strike points around the current price."""
    atm_iv: float           # IV at-the-money
    put_skew_iv: float      # IV at strike ATM - 1σ
    call_skew_iv: float     # IV at strike ATM + 1σ


@dataclass(frozen=True)
class TickerSnapshot:
    """Per-ticker state at a point in time."""
    ticker: str
    last_price: float
    ohlcv_daily: list[OHLCV]      # ~60 bars
    ohlcv_hourly: list[OHLCV]     # 24 bars (last day, hourly)
    iv_rank: float                # 0-100 percentile vs trailing 252 days
    iv_percentile: float          # 0-100 percentile vs absolute scale
    skew: SkewSnapshot
    realized_vol_30d: float       # decimal (0.18 = 18%)


@dataclass(frozen=True)
class MarketState:
    """Point-in-time snapshot of the full universe.

    Note: `frozen=True` prevents reassigning the dataclass fields, but
    the inner `tickers` and `correlations` dicts are still Python-mutable.
    By convention, callers MUST NOT mutate them — treat MarketState as
    a read-only snapshot. The stub generator returns a fresh MarketState
    per `snapshot()` call, so no caller should ever need to mutate.
    """
    timestamp: datetime
    tickers: dict[str, TickerSnapshot]
    correlations: dict[tuple[str, str], float]  # symmetric; key (a, b) with a < b

    def to_dict(self) -> dict:
        """Return a JSON-ready dict representation.

        Datetimes serialize to ISO-8601 strings; tuple correlation keys
        flatten to "A_B" string keys (so the dict is `json.dumps`-able).
        Used by ATHENA to embed market state in the LLM user prompt.
        """
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        for ticker_data in d["tickers"].values():
            for bar in ticker_data["ohlcv_daily"]:
                bar["timestamp"] = bar["timestamp"].isoformat()
            for bar in ticker_data["ohlcv_hourly"]:
                bar["timestamp"] = bar["timestamp"].isoformat()
        d["correlations"] = {
            f"{a}_{b}": v for (a, b), v in self.correlations.items()
        }
        return d


# ── Abstract interface ────────────────────────────────────────────────────────

class DataLayer(ABC):
    """Contract for any data source the real agents query.

    Concrete impls:
      - StubDataLayer (Sprint 3): seeded synthetic data.
      - SchwabDataLayer (Sprint 5): real broker API.
    """

    @abstractmethod
    def snapshot(self) -> MarketState:
        """Return the current market state for the full ticker universe."""
