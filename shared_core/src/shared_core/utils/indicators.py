"""
Common technical / volatility indicators used by both systems.

These are determinístic calculations — no LLM, no statefulness.
"""

from __future__ import annotations

import statistics
from typing import Sequence


def iv_rank(current_iv: float, iv_history: Sequence[float]) -> float:
    """
    IV Rank: where current IV sits between min and max of historical IV.

    Formula: (current - min) / (max - min) * 100

    Returns 0-100. 100 means current IV is at the highest point in the lookback.
    Common lookback: 252 trading days (1 year).
    """
    if not iv_history:
        return 50.0  # No data — return neutral

    iv_min = min(iv_history)
    iv_max = max(iv_history)

    if iv_max == iv_min:
        return 50.0

    rank = (current_iv - iv_min) / (iv_max - iv_min) * 100
    return max(0.0, min(100.0, rank))


def iv_percentile(current_iv: float, iv_history: Sequence[float]) -> float:
    """
    IV Percentile: % of days in lookback where IV was BELOW current.

    Different from IV Rank — IV Percentile counts days, IV Rank uses min/max.
    Generally more robust to outliers than IV Rank.
    """
    if not iv_history:
        return 50.0

    days_below = sum(1 for iv in iv_history if iv < current_iv)
    return (days_below / len(iv_history)) * 100


def realized_volatility(
    prices: Sequence[float],
    annualization_factor: float = 252,
) -> float:
    """
    Realized volatility from price series.

    Args:
        prices: Sequence of prices (close-to-close)
        annualization_factor: 252 for daily, 52 for weekly, etc.

    Returns:
        Annualized volatility as decimal (e.g., 0.25 for 25%).
    """
    if len(prices) < 2:
        return 0.0

    log_returns = [
        (prices[i] / prices[i - 1]) - 1
        for i in range(1, len(prices))
    ]

    if not log_returns:
        return 0.0

    daily_std = statistics.stdev(log_returns) if len(log_returns) > 1 else 0.0
    return daily_std * (annualization_factor**0.5)


def volatility_risk_premium(implied_vol: float, realized_vol: float) -> float:
    """
    VRP = Implied Vol - Realized Vol

    Positive VRP: market is pricing more vol than realized (good for sellers)
    Negative VRP: market underprices vol (good for buyers)
    """
    return implied_vol - realized_vol


def percentile_of(value: float, history: Sequence[float]) -> float:
    """Return the percentile (0-100) of value within history."""
    if not history:
        return 50.0
    below = sum(1 for h in history if h < value)
    return (below / len(history)) * 100


def relative_strength(asset_prices: Sequence[float], benchmark_prices: Sequence[float]) -> float:
    """
    Relative strength of asset vs benchmark over the same period.

    > 1.0 means asset outperformed benchmark
    < 1.0 means asset underperformed
    """
    if len(asset_prices) < 2 or len(benchmark_prices) < 2:
        return 1.0

    asset_return = asset_prices[-1] / asset_prices[0]
    benchmark_return = benchmark_prices[-1] / benchmark_prices[0]

    if benchmark_return == 0:
        return 1.0

    return asset_return / benchmark_return


def relative_volume(current_volume: float, avg_volume: float) -> float:
    """
    Relative volume = current / average.

    > 1.5: above-average activity
    > 2.0: significant institutional interest
    > 3.0: unusual activity
    """
    if avg_volume == 0:
        return 1.0
    return current_volume / avg_volume


def average_true_range(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float:
    """
    ATR — Average True Range. Measures volatility in price units.

    Used by Apollo for swing equity stops (typically 1.5-2x ATR).
    """
    if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
        return 0.0

    true_ranges = []
    for i in range(1, len(highs)):
        high_low = highs[i] - lows[i]
        high_close_prev = abs(highs[i] - closes[i - 1])
        low_close_prev = abs(lows[i] - closes[i - 1])
        tr = max(high_low, high_close_prev, low_close_prev)
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return statistics.mean(true_ranges) if true_ranges else 0.0

    return statistics.mean(true_ranges[-period:])
