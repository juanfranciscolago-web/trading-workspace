"""
PortfolioSnapshot — estado inmutable del portfolio en un instante.

Tres capas:
  PortfolioSnapshot    — modelo de datos puro (frozen dataclass), sin I/O
  SnapshotBuilder      — lee portfolio.positions de la DB y construye el snapshot
  CachedSnapshotBuilder — wrapper con TTL cache (default 5s)

Los checks de ATLAS reciben PortfolioSnapshot como argumento → puro y testeable.
El consumer crea el snapshot antes de invocar atlas_core.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Sequence

logger = logging.getLogger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PositionView:
    """Vista plana de una posición para los checks de ATLAS."""
    ticker: str
    asset_class: str
    strategy_type: str | None
    market_value_usd: Decimal   # abs(qty) * current_price (o entry_price si no hay precio actual)
    quantity: int
    delta: Decimal              # en $, aprox qty * delta_per_share * share_price
    vega: Decimal               # en $ por punto de IV (negativo = short vega)
    theta: Decimal


@dataclass(frozen=True)
class PortfolioSnapshot:
    """
    Estado completo del portfolio en un instante.

    Todos los campos son inmutables. La snapshot_id (SHA-256) identifica
    de forma única el estado del portfolio y sirve como FK en atlas.portfolio_snapshots.
    """
    positions: tuple[PositionView, ...]

    # Aggregates
    nav_usd: Decimal
    cash_usd: Decimal
    buying_power_used_pct: float
    portfolio_beta: float
    vega_total: float           # suma de vega de todas las posiciones (negativo = corto vega neto)

    # PnL
    pnl_daily_usd: Decimal
    pnl_daily_pct: float        # pnl_daily_usd / nav_usd * 100
    pnl_weekly_pct: float
    pnl_monthly_pct: float
    drawdown_from_peak_pct: float  # negativo = pérdida desde peak

    # Metadata
    snapshot_at: datetime
    snapshot_id: str            # SHA-256 — ver snapshot_hash()

    # ── Computed helpers ──────────────────────────────────────────────────────

    def exposure_pct(self, ticker: str) -> float:
        """Exposición actual al ticker como % del NAV."""
        if not self.nav_usd:
            return 0.0
        total = sum(
            float(p.market_value_usd)
            for p in self.positions
            if p.ticker.upper() == ticker.upper()
        )
        return total / float(self.nav_usd) * 100

    def sector_exposure_pct(self, tickers_in_sector: frozenset[str]) -> float:
        """Exposición agregada a todos los tickers del sector."""
        if not self.nav_usd:
            return 0.0
        total = sum(
            float(p.market_value_usd)
            for p in self.positions
            if p.ticker.upper() in {t.upper() for t in tickers_in_sector}
        )
        return total / float(self.nav_usd) * 100


# ── Hash ──────────────────────────────────────────────────────────────────────

def snapshot_hash(
    positions: Sequence[PositionView],
    cash_usd: Decimal,
    pnl_daily_usd: Decimal,
    snapshot_at: datetime,
) -> str:
    """
    Genera un SHA-256 determinista del estado del portfolio.

    Componentes del hash:
    - Posiciones ordenadas por ticker: 'TICKER|qty|entry_market_value'
    - cash_usd redondeado a 2 decimales
    - pnl_daily_usd redondeado a 2 decimales (evita floating-point noise)
    - timestamp truncado al minuto (dos validaciones en el mismo minuto = mismo hash)
    """
    sorted_pos = sorted(positions, key=lambda p: (p.ticker.upper(), p.quantity))
    parts = [
        f"{p.ticker.upper()}|{p.quantity}|{float(p.market_value_usd):.2f}"
        for p in sorted_pos
    ]
    minute_ts = snapshot_at.replace(second=0, microsecond=0).isoformat()
    # PnL truncated (floor) to 2dp to absorb floating-point noise
    pnl_rounded = Decimal(str(pnl_daily_usd)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    canonical = (
        ";".join(parts)
        + f"|cash={float(cash_usd):.2f}"
        + f"|pnl={pnl_rounded}"
        + f"|ts={minute_ts}"
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Builder ───────────────────────────────────────────────────────────────────

class SnapshotBuilder:
    """
    Lee portfolio.positions y portfolio.snapshots de la DB,
    construye un PortfolioSnapshot.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    def build(self) -> PortfolioSnapshot:
        with self._pool.connection() as conn:
            positions = self._load_positions(conn)
            agg = self._load_latest_aggregates(conn)

        now = datetime.now(timezone.utc)
        nav = agg["nav_usd"]
        cash = agg["cash_usd"]
        pnl_daily = agg["pnl_daily_usd"]

        sid = snapshot_hash(positions, cash, pnl_daily, now)

        return PortfolioSnapshot(
            positions=tuple(positions),
            nav_usd=nav,
            cash_usd=cash,
            buying_power_used_pct=agg["buying_power_used_pct"],
            portfolio_beta=agg["portfolio_beta"],
            vega_total=agg["vega_total"],
            pnl_daily_usd=pnl_daily,
            pnl_daily_pct=float(pnl_daily) / float(nav) * 100 if nav else 0.0,
            pnl_weekly_pct=agg["pnl_weekly_pct"],
            pnl_monthly_pct=agg["pnl_monthly_pct"],
            drawdown_from_peak_pct=agg["drawdown_from_peak_pct"],
            snapshot_at=now,
            snapshot_id=sid,
        )

    @staticmethod
    def _load_positions(conn) -> list[PositionView]:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ticker, asset_class, strategy_type, quantity,
                       COALESCE(current_price, entry_price) AS price,
                       COALESCE(delta, 0) AS delta,
                       COALESCE(vega, 0)  AS vega,
                       COALESCE(theta, 0) AS theta
                FROM portfolio.positions
                WHERE is_open = TRUE
                ORDER BY ticker
                """
            )
            rows = cur.fetchall()

        positions = []
        for ticker, asset_class, strategy_type, qty, price, delta, vega, theta in rows:
            market_value = Decimal(str(abs(qty))) * Decimal(str(price))
            positions.append(PositionView(
                ticker=ticker,
                asset_class=asset_class,
                strategy_type=strategy_type,
                market_value_usd=market_value,
                quantity=qty,
                delta=Decimal(str(delta)),
                vega=Decimal(str(vega)),
                theta=Decimal(str(theta)),
            ))
        return positions

    @staticmethod
    def _load_latest_aggregates(conn) -> dict:
        """Read most recent portfolio snapshot for aggregate metrics."""
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT total_nav_usd, cash_available_usd, buying_power_used_pct,
                       COALESCE(portfolio_beta, 0),
                       COALESCE(vega_total, 0),
                       COALESCE(drawdown_from_peak_pct, 0)
                FROM portfolio.snapshots
                ORDER BY snapshot_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()

        if row is None:
            # No snapshot yet — bootstrap with cash-only defaults
            return {
                "nav_usd": Decimal("1000000.00"),
                "cash_usd": Decimal("1000000.00"),
                "buying_power_used_pct": 0.0,
                "portfolio_beta": 0.0,
                "vega_total": 0.0,
                "pnl_daily_usd": Decimal("0.00"),
                "pnl_weekly_pct": 0.0,
                "pnl_monthly_pct": 0.0,
                "drawdown_from_peak_pct": 0.0,
            }

        nav, cash, bp_pct, beta, vega, dd = row
        return {
            "nav_usd": Decimal(str(nav)),
            "cash_usd": Decimal(str(cash)),
            "buying_power_used_pct": float(bp_pct or 0),
            "portfolio_beta": float(beta),
            "vega_total": float(vega),
            "pnl_daily_usd": Decimal("0.00"),   # Sprint 3+: from daily_pnl table
            "pnl_weekly_pct": 0.0,              # Sprint 3+
            "pnl_monthly_pct": 0.0,             # Sprint 3+
            "drawdown_from_peak_pct": float(dd),
        }


# ── Cached builder ────────────────────────────────────────────────────────────

class CachedSnapshotBuilder:
    """
    Wrapper con TTL cache alrededor de SnapshotBuilder.

    Dos validaciones dentro de la misma ventana de TTL usan el mismo snapshot
    (mismo snapshot_id). Default TTL: 5 segundos.
    """

    def __init__(self, builder: SnapshotBuilder, ttl_seconds: float = 5.0) -> None:
        self._builder = builder
        self._ttl = ttl_seconds
        self._cached: PortfolioSnapshot | None = None
        self._cached_at: float = 0.0

    def get(self) -> PortfolioSnapshot:
        now = time.monotonic()
        if self._cached is None or (now - self._cached_at) > self._ttl:
            self._cached = self._builder.build()
            self._cached_at = now
            logger.debug("Portfolio snapshot refreshed (id=%s)", self._cached.snapshot_id[:8])
        return self._cached

    def invalidate(self) -> None:
        """Force refresh on next get()."""
        self._cached = None
