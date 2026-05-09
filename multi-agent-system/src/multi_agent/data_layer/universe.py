"""
TICKER_UNIVERSE — fixed list of tickers the ATHENA stub data layer simulates.

Choice rationale (per ADR-002 open question):
- 6 tickers, mix of broad index ETFs (SPY/QQQ/IWM) and tech mega-caps
  (NVDA/AAPL/MSFT).
- All have high option liquidity, which is what ATHENA's strategies (CSP,
  credit spreads, iron condors) need.
- Mix of vol regimes: low-vol indices (SPY ~16%), high-vol mega-cap
  (NVDA ~50%) so ATHENA encounters both selling-friendly and
  selling-unfriendly setups.
- iv_rank_bias spread (35-70) ensures variety across snapshots: some
  tickers usually have IV ranks high enough to interest ATHENA, others
  usually too low.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TickerProfile:
    """Baseline parameters per ticker for seeded synthetic data generation."""
    ticker: str
    base_price: float       # USD — starting close for OHLCV generation
    annualized_vol: float   # decimal (0.16 = 16%) — random walk amplitude
    drift: float            # annualized expected return decimal
    iv_rank_bias: float     # 0-100 — baseline IV rank percentile center


TICKER_UNIVERSE: dict[str, TickerProfile] = {
    "SPY":  TickerProfile("SPY",  base_price=440.0, annualized_vol=0.16, drift=0.08, iv_rank_bias=35.0),
    "QQQ":  TickerProfile("QQQ",  base_price=375.0, annualized_vol=0.22, drift=0.10, iv_rank_bias=45.0),
    "IWM":  TickerProfile("IWM",  base_price=190.0, annualized_vol=0.24, drift=0.05, iv_rank_bias=55.0),
    "NVDA": TickerProfile("NVDA", base_price=480.0, annualized_vol=0.52, drift=0.20, iv_rank_bias=70.0),
    "AAPL": TickerProfile("AAPL", base_price=180.0, annualized_vol=0.28, drift=0.10, iv_rank_bias=40.0),
    "MSFT": TickerProfile("MSFT", base_price=370.0, annualized_vol=0.26, drift=0.10, iv_rank_bias=50.0),
}
