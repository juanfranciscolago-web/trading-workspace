#!/usr/bin/env python3
"""
Seed del portfolio sintético para testing de ATLAS en Sprint 2A.

Inserta 10 posiciones realistas en portfolio.positions y un snapshot inicial
en portfolio.snapshots. NAV asumido: $1,000,000.

Uso:
    python scripts/seed_portfolio.py
    DATABASE_URL=postgresql://... python scripts/seed_portfolio.py

Si las posiciones ya existen (mismo position_id), hace UPSERT — seguro re-ejecutar.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import psycopg2
import psycopg2.extras

psycopg2.extras.register_uuid()

DSN = os.environ.get("DATABASE_URL", "postgresql://trader:trader@localhost:5432/trading")

NAV_USD = 1_000_000.00
ENTRY_TS = datetime(2026, 4, 1, 14, 30, 0, tzinfo=timezone.utc)

# ── Positions ─────────────────────────────────────────────────────────────────
# 10 posiciones: mix equity + 1 CSP opciones (NVDA)
# Cada entry: (position_id, source, ticker, asset_class, strategy_type,
#              qty, entry_price, current_price, delta, vega, theta, unrealized_pnl)

POSITIONS = [
    # tech_mega_cap bucket
    {
        "position_id": "seed-msft-equity-001",
        "ticker": "MSFT",
        "asset_class": "equity",
        "strategy_type": "SWING_EQUITY",
        "quantity": 100,
        "entry_price": 440.00,
        "current_price": 442.50,
        "delta": 100.0,        # 1.0 delta per share, 100 shares
        "vega": 0.0,
        "theta": 0.0,
        "unrealized_pnl": 250.00,  # 100 * (442.50 - 440.00)
    },
    {
        "position_id": "seed-aapl-equity-001",
        "ticker": "AAPL",
        "asset_class": "equity",
        "strategy_type": "SWING_EQUITY",
        "quantity": 80,
        "entry_price": 220.00,
        "current_price": 218.75,
        "delta": 80.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealized_pnl": -100.00,
    },
    {
        "position_id": "seed-googl-equity-001",
        "ticker": "GOOGL",
        "asset_class": "equity",
        "strategy_type": "SWING_EQUITY",
        "quantity": 30,
        "entry_price": 175.00,
        "current_price": 177.00,
        "delta": 30.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealized_pnl": 60.00,
    },
    # semis bucket — equity
    {
        "position_id": "seed-nvda-equity-001",
        "ticker": "NVDA",
        "asset_class": "equity",
        "strategy_type": "SWING_EQUITY",
        "quantity": 50,
        "entry_price": 850.00,
        "current_price": 862.00,
        "delta": 50.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealized_pnl": 600.00,
    },
    # semis bucket — CSP opciones (introduce vega real al portfolio)
    {
        "position_id": "seed-nvda-csp-001",
        "ticker": "NVDA",
        "asset_class": "option",
        "strategy_type": "CSP",
        "quantity": -2,          # 2 contratos short (vendidos)
        "entry_price": 800.00,   # strike $800 put
        "current_price": 800.00,
        "delta": -30.0,          # short put: negative delta (≈0.15 delta * 100 * 2 contratos)
        "vega": 480.0,           # short put: positive vega notation = we LOSE when vol rises
                                 # almacenado positivo, pero es short vega
        "theta": 45.0,           # theta positivo = recibimos theta decay diario
        "unrealized_pnl": 180.00,
    },
    # broad_market bucket
    {
        "position_id": "seed-spy-equity-001",
        "ticker": "SPY",
        "asset_class": "equity",
        "strategy_type": "SWING_EQUITY",
        "quantity": 40,
        "entry_price": 530.00,
        "current_price": 532.00,
        "delta": 40.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealized_pnl": 80.00,
    },
    {
        "position_id": "seed-qqq-equity-001",
        "ticker": "QQQ",
        "asset_class": "equity",
        "strategy_type": "SWING_EQUITY",
        "quantity": 15,
        "entry_price": 470.00,
        "current_price": 471.50,
        "delta": 15.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealized_pnl": 22.50,
    },
    # energy bucket
    {
        "position_id": "seed-xle-etf-001",
        "ticker": "XLE",
        "asset_class": "equity",
        "strategy_type": "SECTOR_ROTATION",
        "quantity": 100,
        "entry_price": 90.00,
        "current_price": 89.20,
        "delta": 100.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealized_pnl": -80.00,
    },
    # defensives bucket
    {
        "position_id": "seed-gld-etf-001",
        "ticker": "GLD",
        "asset_class": "equity",
        "strategy_type": "SWING_EQUITY",
        "quantity": 50,
        "entry_price": 215.00,
        "current_price": 216.50,
        "delta": 50.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealized_pnl": 75.00,
    },
    # crypto_correlated bucket
    {
        "position_id": "seed-coin-equity-001",
        "ticker": "COIN",
        "asset_class": "equity",
        "strategy_type": "SWING_EQUITY",
        "quantity": 20,
        "entry_price": 240.00,
        "current_price": 238.50,
        "delta": 20.0,
        "vega": 0.0,
        "theta": 0.0,
        "unrealized_pnl": -30.00,
    },
]

# Portfolio aggregates (computed from positions + cash)
# Market value: suma de abs(qty)*current_price
_MARKET_VALUE = sum(abs(p["quantity"]) * p["current_price"] for p in POSITIONS)
_CASH = NAV_USD - _MARKET_VALUE
_TOTAL_PNL = sum(p["unrealized_pnl"] for p in POSITIONS)
_VEGA_TOTAL = -sum(p["vega"] for p in POSITIONS)   # negativo = short vega neto
_DELTA_TOTAL = sum(p["delta"] for p in POSITIONS)
_THETA_TOTAL = sum(p["theta"] for p in POSITIONS)

# Rough portfolio beta: weighted average delta / NAV (in dollar terms, SPY proxy)
# Simplified: ignore options delta for beta calculation
_BETA = round(_DELTA_TOTAL / (NAV_USD / 530.0) / 100, 4)  # using SPY=530 as proxy

_BUYING_POWER_USED = round(_MARKET_VALUE / NAV_USD * 100, 2)


def seed(dsn: str = DSN) -> None:
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    try:
        _seed_positions(conn)
        _seed_snapshot(conn)
        conn.commit()
        print(f"✓ Seeded {len(POSITIONS)} positions")
        print(f"  Market value: ${_MARKET_VALUE:,.2f} ({_BUYING_POWER_USED:.1f}% NAV)")
        print(f"  Cash: ${_CASH:,.2f}")
        print(f"  Total unrealized PnL: ${_TOTAL_PNL:,.2f}")
        print(f"  Portfolio beta (est): {_BETA}")
        print(f"  Vega total (short): {_VEGA_TOTAL:,.0f}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _seed_positions(conn) -> None:
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        for p in POSITIONS:
            cur.execute(
                """
                INSERT INTO portfolio.positions (
                    position_id, source, ticker, asset_class, strategy_type,
                    quantity, entry_price, current_price, entry_timestamp,
                    delta, vega, theta, unrealized_pnl, is_open, updated_at
                ) VALUES (
                    %s, 'seed', %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, TRUE, %s
                )
                ON CONFLICT (position_id) DO UPDATE SET
                    current_price  = EXCLUDED.current_price,
                    unrealized_pnl = EXCLUDED.unrealized_pnl,
                    delta          = EXCLUDED.delta,
                    vega           = EXCLUDED.vega,
                    theta          = EXCLUDED.theta,
                    updated_at     = EXCLUDED.updated_at
                """,
                (
                    p["position_id"],
                    p["ticker"], p["asset_class"], p["strategy_type"],
                    p["quantity"], p["entry_price"], p["current_price"], ENTRY_TS,
                    p["delta"], p["vega"], p["theta"], p["unrealized_pnl"],
                    now,
                ),
            )


def _seed_snapshot(conn) -> None:
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO portfolio.snapshots (
                snapshot_at, total_nav_usd, cash_available_usd,
                buying_power_used_pct, portfolio_beta,
                vega_total, delta_total, theta_total,
                tech_concentration_pct, drawdown_from_peak_pct,
                risk_mode, open_positions_count
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                now,
                NAV_USD,
                _CASH,
                _BUYING_POWER_USED,
                _BETA,
                _VEGA_TOTAL,
                _DELTA_TOTAL,
                _THETA_TOTAL,
                # tech_concentration: MSFT+AAPL+GOOGL+NVDA market value / NAV
                round(
                    sum(
                        abs(p["quantity"]) * p["current_price"]
                        for p in POSITIONS
                        if p["ticker"] in ("MSFT", "AAPL", "GOOGL", "NVDA")
                    ) / NAV_USD * 100,
                    2,
                ),
                -2.1,    # drawdown from peak (synthetic)
                "GREEN",
                len(POSITIONS),
            ),
        )


if __name__ == "__main__":
    print(f"Seeding portfolio to {DSN.split('@')[-1]}...")
    seed()
