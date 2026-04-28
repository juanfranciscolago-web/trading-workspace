"""
Shared domain models — used by both Eolo and the multi-agent system.

These are the canonical representations of trading entities. Both systems
must produce/consume objects of these types when interacting via shared-core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Optional


# =============================================================================
# Enums
# =============================================================================

class TradeSource(str, Enum):
    """Identifies which system originated a trade. Critical for attribution."""
    EOLO_V1 = "eolo_v1"
    EOLO_V2_SPX = "eolo_v2_spx"
    EOLO_CRYPTO = "eolo_crypto"
    MULTI_AGENT_ATHENA = "multi_agent_athena"
    MULTI_AGENT_APOLLO = "multi_agent_apollo"
    MULTI_AGENT_HERMES = "multi_agent_hermes"
    MULTI_AGENT_NYX = "multi_agent_nyx"
    MULTI_AGENT_VESTA = "multi_agent_vesta"
    HUMAN_VIA_EOLO = "human_via_eolo"
    HUMAN_DIRECT = "human_direct"


class AssetClass(str, Enum):
    EQUITY = "equity"
    OPTION = "option"
    FUTURE = "future"
    CRYPTO = "crypto"
    ETF = "etf"


class Direction(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class TradeStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    ERROR = "error"


# =============================================================================
# Domain models
# =============================================================================

@dataclass
class Instrument:
    """Canonical representation of any tradeable instrument."""
    symbol: str
    asset_class: AssetClass

    # Option-specific fields (None for non-options)
    option_type: Optional[OptionType] = None
    strike: Optional[Decimal] = None
    expiration: Optional[date] = None

    # Underlying for derivatives
    underlying: Optional[str] = None

    @property
    def occ_symbol(self) -> Optional[str]:
        """Generate OCC option symbol if this is an option."""
        if self.asset_class != AssetClass.OPTION:
            return None
        if not all([self.underlying, self.expiration, self.option_type, self.strike]):
            return None
        # OCC format: ROOT_YYMMDD_C/P_STRIKE
        exp_str = self.expiration.strftime("%y%m%d")
        opt_char = "C" if self.option_type == OptionType.CALL else "P"
        strike_int = int(self.strike * 1000)
        return f"{self.underlying}{exp_str}{opt_char}{strike_int:08d}"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "option_type": self.option_type.value if self.option_type else None,
            "strike": float(self.strike) if self.strike else None,
            "expiration": self.expiration.isoformat() if self.expiration else None,
            "underlying": self.underlying,
        }


@dataclass
class Greeks:
    """Option Greeks. All values per contract (not aggregate)."""
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    iv: float = 0.0  # Implied volatility

    def aggregate(self, quantity: int, multiplier: int = 100) -> "Greeks":
        """Scale by quantity * multiplier (default 100 for equity options)."""
        factor = quantity * multiplier
        return Greeks(
            delta=self.delta * factor,
            gamma=self.gamma * factor,
            theta=self.theta * factor,
            vega=self.vega * factor,
            rho=self.rho * factor,
            iv=self.iv,  # IV doesn't aggregate
        )


@dataclass
class Position:
    """An open position in any system."""
    position_id: str
    source: TradeSource
    instrument: Instrument
    quantity: int  # Negative for short
    entry_price: Decimal
    entry_timestamp: datetime
    current_price: Optional[Decimal] = None

    # Optional fields
    strategy: Optional[str] = None
    thesis: Optional[str] = None
    stop_price: Optional[Decimal] = None
    target_price: Optional[Decimal] = None
    greeks: Optional[Greeks] = None
    metadata: dict = field(default_factory=dict)

    @property
    def is_long(self) -> bool:
        return self.quantity > 0

    @property
    def is_short(self) -> bool:
        return self.quantity < 0

    @property
    def absolute_quantity(self) -> int:
        return abs(self.quantity)

    def unrealized_pnl(self) -> Optional[Decimal]:
        """Calculate unrealized P&L if current price is available."""
        if self.current_price is None:
            return None
        multiplier = 100 if self.instrument.asset_class == AssetClass.OPTION else 1
        diff = (self.current_price - self.entry_price) * multiplier
        return diff * self.quantity


@dataclass
class TradeOrder:
    """A trade request — used for risk validation BEFORE execution."""
    source: TradeSource
    instrument: Instrument
    direction: Direction
    quantity: int
    expected_price: Optional[Decimal] = None
    strategy: Optional[str] = None
    order_type: str = "limit"  # "market", "limit", "stop"
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    time_in_force: str = "DAY"
    metadata: dict = field(default_factory=dict)


@dataclass
class TradeExecution:
    """Record of an executed trade (or attempted)."""
    execution_id: str
    source: TradeSource
    instrument: Instrument
    direction: Direction
    quantity: int
    fill_price: Optional[Decimal]
    fill_timestamp: Optional[datetime]
    status: TradeStatus
    venue: str = "SCHWAB"
    commissions: Decimal = Decimal("0")
    slippage_pct: Optional[float] = None
    strategy: Optional[str] = None
    error_message: Optional[str] = None
    metadata: dict = field(default_factory=dict)
