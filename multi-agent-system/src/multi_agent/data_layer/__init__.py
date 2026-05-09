"""Data layer for the multi-agent trading system.

Sprint 3 only ships StubDataLayer (synthetic seeded data); Sprint 5 will add
SchwabDataLayer hitting the real broker API. Both implement the DataLayer
interface from `interfaces.py`. ATHENA and future real agents call
`data_layer.snapshot()` to get a `MarketState` for the current universe.
"""
from __future__ import annotations

from .interfaces import DataLayer, MarketState, OHLCV, SkewSnapshot, TickerSnapshot
from .stub_data_layer import StubDataLayer
from .universe import TICKER_UNIVERSE, TickerProfile

__all__ = [
    "DataLayer",
    "MarketState",
    "OHLCV",
    "SkewSnapshot",
    "StubDataLayer",
    "TICKER_UNIVERSE",
    "TickerProfile",
    "TickerSnapshot",
]
