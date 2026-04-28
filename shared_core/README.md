# shared-core

Common infrastructure for the **Eolo + multi-agent trading system**.

This Python package contains everything that BOTH the legacy Eolo system and the new multi-agent system need to share:

- **Broker clients** (Schwab, crypto exchanges)
- **Data clients** (market data, news, on-chain)
- **Storage layer** (PostgreSQL, Redis)
- **Risk validation** (ATLAS client for cross-system risk coordination)
- **Domain models** (Position, Trade, Greeks, etc.)
- **Common indicators and calculators**

## Why This Package Exists

The trading workspace contains two systems that both need to:
- Connect to Schwab API
- Read market data from Polygon, Benzinga
- Calculate Greeks
- Compute IV Rank, IV Percentile, ATR
- Persist trades to a common database
- Coordinate risk via ATLAS

Without `shared-core`, both systems would duplicate this code, leading to:
- Two Schwab API authentication flows competing for tokens
- Two Polygon subscriptions ($400-800/month wasted)
- Inconsistent Greeks calculations
- No way to see aggregate risk across both systems

`shared-core` is the foundation. **Eolo and multi-agent both import from here.**

## Architecture

```
trading-workspace/
├── shared-core/              # ← This package
├── eolo-legacy/              # Imports from shared-core
└── multi-agent-system/       # Imports from shared-core
```

## Installation

In each consumer project (Eolo or multi-agent):

```bash
pip install -e ../shared-core
```

The `-e` (editable) flag means changes to `shared-core` are immediately visible in both consumers without reinstalling.

## Quick Start

### Domain models

```python
from shared_core.models import (
    Instrument, AssetClass, OptionType, TradeSource, TradeOrder, Direction
)
from datetime import date
from decimal import Decimal

# Create an option
msft_put = Instrument(
    symbol="MSFT_PUT_410",
    asset_class=AssetClass.OPTION,
    option_type=OptionType.PUT,
    strike=Decimal("410"),
    expiration=date(2026, 6, 19),
    underlying="MSFT",
)

# Create a trade order
order = TradeOrder(
    source=TradeSource.MULTI_AGENT_ATHENA,
    instrument=msft_put,
    direction=Direction.SELL,
    quantity=10,
    expected_price=Decimal("4.85"),
    strategy="csp",
)
```

### Risk validation (ATLAS client)

```python
from shared_core.risk import get_atlas_client

atlas = get_atlas_client()
risk_check = atlas.validate_trade(order=order)

if risk_check.approved:
    # Execute via Schwab client
    pass
elif risk_check.approved_with_conditions:
    # Apply conditions before executing
    for condition in risk_check.conditions:
        print(f"Condition: {condition.description}")
elif risk_check.blocked:
    print(f"Blocked: {risk_check.reason}")
```

### Schwab client (shared by both systems)

```python
from shared_core.brokers import SchwabClient

client = SchwabClient.from_env(paper_trading=True)
quote = client.get_quote("MSFT")
chain = client.get_options_chain("MSFT", expiration="2026-06-19")
```

### Greeks calculation

```python
from shared_core.utils import (
    BlackScholesInput, calculate_greeks, time_to_expiry_years
)
from datetime import date

inputs = BlackScholesInput(
    underlying_price=415.30,
    strike=410,
    time_to_expiry_years=time_to_expiry_years(date.today(), date(2026, 6, 19)),
    risk_free_rate=0.05,
    volatility=0.25,
    option_type="put",
)

greeks = calculate_greeks(inputs)
print(f"Delta: {greeks.delta:.3f}")
print(f"Theta: {greeks.theta:.3f} (per day)")
```

### Indicators

```python
from shared_core.utils import iv_rank, iv_percentile, realized_volatility

# Last 252 days of IV history
iv_history = [0.20, 0.22, 0.18, ...]  # from your data layer
current_iv = 0.25

print(f"IV Rank: {iv_rank(current_iv, iv_history):.1f}")
print(f"IV Percentile: {iv_percentile(current_iv, iv_history):.1f}")
```

### Trade logging (cross-system attribution)

```python
from shared_core.storage import TradeLogger
from shared_core.models import TradeExecution, TradeStatus

logger = TradeLogger.from_env()
logger.init_schema()  # Run once on setup

# After executing a trade
execution = TradeExecution(
    execution_id="exec_12345",
    source=TradeSource.EOLO_V1,
    instrument=msft_put,
    direction=Direction.SELL,
    quantity=10,
    fill_price=Decimal("4.82"),
    fill_timestamp=datetime.now(timezone.utc),
    status=TradeStatus.FILLED,
)
logger.log_execution(execution)

# Query for performance attribution
eolo_trades_30d = logger.query_trades(
    source=TradeSource.EOLO_V1,
    days=30,
)

# Aggregate attribution summary
summary = logger.get_attribution_summary(days=30)
for source, stats in summary.items():
    print(f"{source}: {stats['trade_count']} trades, "
          f"avg slippage {stats['avg_slippage_pct']:.2f}%")
```

### Event bus (cross-system coordination)

```python
from shared_core.messaging import (
    EventPublisher, EventSubscriber, Event, EventTypes, Channels
)

# Publishing an event from Eolo
publisher = EventPublisher.from_env()
publisher.publish(
    Channels.SYSTEM_EVENTS,
    Event(
        event_type=EventTypes.TRADE_EXECUTED,
        source="eolo_v1",
        payload={"symbol": "MSFT", "quantity": 10, "price": 4.82},
    )
)

# Subscribing in multi-agent
def on_trade_event(event: Event):
    print(f"Received {event.event_type} from {event.source}")

subscriber = EventSubscriber.from_env()
subscriber.subscribe(Channels.SYSTEM_EVENTS, on_trade_event)
subscriber.start()  # Listens in background thread
```

## Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/trading

# Redis
REDIS_URL=redis://localhost:6379/0

# Schwab
SCHWAB_API_KEY=...
SCHWAB_API_SECRET=...
SCHWAB_REFRESH_TOKEN=...

# ATLAS service
ATLAS_ENDPOINT=http://localhost:8001
```

## Module Structure

```
shared_core/
├── __init__.py              # Re-exports common types
├── models.py                # Domain models (Position, Trade, Greeks, etc.)
├── brokers/
│   └── schwab_client.py     # Unified Schwab API wrapper
├── data/                    # Market data clients (Polygon, Benzinga, etc.)
├── storage/
│   ├── postgres_pool.py     # Connection pooling
│   └── trade_logger.py      # Cross-system trade log
├── utils/
│   ├── greeks_calculator.py # Black-Scholes + Greeks
│   └── indicators.py        # IV Rank, ATR, etc.
├── risk/
│   └── atlas_client.py      # Risk validation client
├── messaging/
│   └── event_bus.py         # Redis pub/sub
└── config/                  # Secrets management
```

## Migration Guide for Eolo

To migrate Eolo to use `shared-core`:

### Step 1: Install package

```bash
cd eolo-legacy
pip install -e ../shared-core
```

### Step 2: Replace Eolo's Schwab wrapper

Find Eolo's existing Schwab integration and replace imports:

```python
# Before (Eolo internal)
from eolo.brokers.schwab import SchwabAPIClient

# After (shared)
from shared_core.brokers import SchwabClient
```

The methods should match (this is why `shared-core/brokers/schwab_client.py` is currently a skeleton — port Eolo's working implementation into it).

### Step 3: Add ATLAS validation pre-execution

In Eolo's order placement code, add the validation hook:

```python
from shared_core.risk import get_atlas_client
from shared_core.models import TradeOrder, TradeSource

atlas = get_atlas_client()

# Build order
order = TradeOrder(
    source=TradeSource.EOLO_V1,
    instrument=instrument,
    direction=direction,
    quantity=quantity,
    strategy="my_strategy",
)

# Validate
risk_check = atlas.validate_trade(order)
if not risk_check.approved and not risk_check.approved_with_conditions:
    log.warning(f"Trade blocked by ATLAS: {risk_check.reason}")
    return

# Apply any conditions
if risk_check.modified_size:
    order.quantity = risk_check.modified_size

# Execute as before
schwab_client.place_order(...)
```

### Step 4: Log to shared trade log

After every execution, log to the shared table:

```python
from shared_core.storage import TradeLogger

logger = TradeLogger.from_env()
logger.log_execution(execution)
```

## Running Tests

```bash
cd shared-core
pip install -e ".[dev]"
pytest tests/ -v
```

Expected: 23/23 tests pass with no real network or DB calls (all mocked or pure logic).

## Status

**Current state (v0.1.0):** Foundation laid out, key abstractions defined.

**TODOs that need real implementation:**
- [ ] Schwab HTTP integration (port from Eolo's working code)
- [ ] AtlasClient HTTP layer (depends on multi-agent ATLAS service being live)
- [ ] Market data clients (Polygon, Benzinga, FRED)
- [ ] Crypto clients (CCXT wrapper)
- [ ] Secrets manager integration (AWS Secrets Manager)
- [ ] Real Batch API support (currently sync calls)

The skeletons are in place; filling them in is incremental work as Sprint 1-2 progresses.
