"""
shared-core — Common infrastructure for the Eolo + multi-agent trading system.

This package contains everything that BOTH systems need to share:
- Broker clients (Schwab, crypto exchanges)
- Data clients (market data, news, on-chain)
- Storage layer (PostgreSQL, Redis)
- Risk validation (ATLAS client)
- Domain models (Position, Trade, Greeks, etc.)
- Common indicators and calculators

Both Eolo and the multi-agent system import from here. This is the foundation
of cross-system coordination.
"""

__version__ = "0.1.0"

# Re-export common types for convenience
from shared_core.models import (
    AssetClass,
    Direction,
    Greeks,
    Instrument,
    OptionType,
    Position,
    TradeExecution,
    TradeOrder,
    TradeSource,
    TradeStatus,
)

__all__ = [
    "AssetClass",
    "Direction",
    "Greeks",
    "Instrument",
    "OptionType",
    "Position",
    "TradeExecution",
    "TradeOrder",
    "TradeSource",
    "TradeStatus",
]
