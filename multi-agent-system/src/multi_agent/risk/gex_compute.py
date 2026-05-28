"""GEX compute pipeline — Tier A signal generation (ADR-011, Sprint 13)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Sequence

from shared_core.utils.greeks_calculator import (
    BlackScholesInput,
    calculate_charm,
    calculate_vanna,
    time_to_expiry_years,
)

logger = logging.getLogger(__name__)

# ── Constants (ADR-011 D4 + D5) ──────────────────────────────────────────
CONTRACT_MULTIPLIER = 100  # standard equity options (F-r ant #4 hardcoded)
DTE_BUCKETS: list[tuple[int, int, str]] = [
    (0, 0, "0DTE"),
    (1, 7, "1-7DTE"),
    (8, 30, "8-30DTE"),
    (31, 60, "31-60DTE"),
    (61, 99999, ">60DTE"),
]

# ── Vanna/Charm defaults (ADR-011 D-ε-7, tech debt Sprint 14+) ──────────
DEFAULT_RISK_FREE_RATE = 0.05  # FRED API tech debt Sprint 14+
DEFAULT_DIVIDEND_YIELD = 0.0   # per-ticker config tech debt Sprint 14+


# ── GexSnapshot dataclass (ADR-011 D8) ────────────────────────────────────
@dataclass(frozen=True)
class GexSnapshot:
    """GEX/Vanna/Charm aggregate snapshot per underlying.

    ADR-011 D8 downstream consumer interface. Sprint 13 gex-a scaffold:
    GEX fully computed, Vanna/Charm init 0.0 (populated Sprint 13 gex-b
    via shared_core.utils.greeks_calculator extension D-ε-6).

    Units: GEX en $ per 1% move (SpotGamma convention per D4).
    """

    underlying: str
    snapshot_at: datetime
    spot: float
    gex_total: float
    gex_per_expiration: dict[str, float]
    gex_per_strike: dict[float, float]
    gamma_flip_point: float | None
    vanna_total: float  # Sprint 13 gex-b populated (D-ε-6)
    charm_total: float  # Sprint 13 gex-b populated (D-ε-6)


# ── Helper functions ─────────────────────────────────────────────────────
def _bucket_for_dte(dte: int) -> str:
    """Map DTE to bucket label per DTE_BUCKETS."""
    for low, high, label in DTE_BUCKETS:
        if low <= dte <= high:
            return label
    return ">60DTE"  # fallback


def _dte_from_expiration(expiration: date, ts: datetime) -> int:
    """Calculate DTE (days to expiration) from snapshot timestamp.

    F-r ant #3: expiration is DATE type, ts is TIMESTAMPTZ.
    DTE = (expiration - ts.date()).days.
    """
    return (expiration - ts.date()).days


# ── 4 aggregation level functions (ADR-011 D5) ───────────────────────────
def compute_gex_per_strike(
    surface_rows: Sequence[dict],
    spot: float,
) -> dict[float, float]:
    """Compute GEX contribution per strike.

    ADR-011 D4 formula: GEX_per_strike =
        (call_gamma × call_OI − put_gamma × put_OI) × spot² × 0.01 × MULTIPLIER

    F-r ant #7: si spot <= 0, log warning + return empty dict.
    F-r ant #4: option_type strings "CALL"/"PUT" verbatim per V007.
    """
    if spot <= 0:
        logger.warning(
            "gex_compute_invalid_spot",
            extra={"event": "gex_compute_invalid_spot", "spot": spot},
        )
        return {}

    spot_squared_pct = spot * spot * 0.01
    gex_by_strike: dict[float, float] = {}

    for row in surface_rows:
        strike = float(row["strike"])
        gamma = float(row["gamma"])
        oi = int(row.get("open_interest", 0))
        option_type = row["option_type"]

        sign = 1.0 if option_type == "CALL" else -1.0
        contribution = sign * gamma * oi * spot_squared_pct * CONTRACT_MULTIPLIER
        gex_by_strike[strike] = gex_by_strike.get(strike, 0.0) + contribution

    return gex_by_strike


def compute_gex_per_expiration(
    surface_rows: Sequence[dict],
    spot: float,
    snapshot_ts: datetime,
) -> dict[str, float]:
    """Compute GEX per DTE bucket.

    Groups by expiration → DTE → bucket → sum GEX contributions.
    """
    if spot <= 0:
        return {}

    spot_squared_pct = spot * spot * 0.01
    gex_by_bucket: dict[str, float] = {b[2]: 0.0 for b in DTE_BUCKETS}

    for row in surface_rows:
        gamma = float(row["gamma"])
        oi = int(row.get("open_interest", 0))
        option_type = row["option_type"]
        expiration = row["expiration"]

        if isinstance(expiration, str):
            expiration = date.fromisoformat(expiration)

        dte = _dte_from_expiration(expiration, snapshot_ts)
        bucket = _bucket_for_dte(dte)

        sign = 1.0 if option_type == "CALL" else -1.0
        contribution = sign * gamma * oi * spot_squared_pct * CONTRACT_MULTIPLIER
        gex_by_bucket[bucket] += contribution

    return gex_by_bucket


def compute_gamma_flip_point(
    gex_per_strike: dict[float, float],
) -> float | None:
    """Find strike where cumulative GEX flips sign (zero-crossing).

    Iterates strikes ascending, accumulates GEX. Returns strike where
    cumulative crosses zero. Returns None if no flip (all positive or
    all negative or empty).

    F-r ant #6: edge cases tested (all positive, all negative, single
    strike, alternating, ATM-only).
    """
    if not gex_per_strike:
        return None

    sorted_strikes = sorted(gex_per_strike.keys())
    cumulative = 0.0
    prev_sign: float | None = None

    for strike in sorted_strikes:
        cumulative += gex_per_strike[strike]
        current_sign = 1.0 if cumulative > 0 else (-1.0 if cumulative < 0 else 0.0)

        if prev_sign is not None and prev_sign != 0 and current_sign != 0:
            if prev_sign != current_sign:
                return strike  # flip detected

        if current_sign != 0:
            prev_sign = current_sign

    return None


def compute_vanna_charm_totals(
    surface_rows: Sequence[dict],
    spot: float,
    snapshot_ts: datetime,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    dividend_yield: float = DEFAULT_DIVIDEND_YIELD,
) -> tuple[float, float]:
    """Aggregate Vanna + Charm totals across strikes, weighted by OI.

    ADR-011 D6 amendment via shared_core greeks_calculator extension.
    Returns (vanna_total, charm_total):
    - vanna_total: per-unit-σ × OI × CONTRACT_MULTIPLIER aggregate.
    - charm_total: per-day × OI × CONTRACT_MULTIPLIER aggregate (Hull
      formula returns per-year, divided by 365 here per D-γ-7).

    F-r ant #1: option_type case translation iv_surface "CALL"/"PUT"
    UPPERCASE → BlackScholesInput "call"/"put" LOWERCASE (D-δ-7).
    F-r ant #3: T<=0 skip iteration defensive.
    """
    if spot <= 0:
        return (0.0, 0.0)

    vanna_total = 0.0
    charm_total = 0.0

    for row in surface_rows:
        strike = float(row["strike"])
        iv = float(row["iv"])
        oi = int(row.get("open_interest", 0))
        option_type = row["option_type"].lower()  # F-r ant #1 case translation (D-δ-7)
        expiration = row["expiration"]
        if isinstance(expiration, str):
            expiration = date.fromisoformat(expiration)

        T = time_to_expiry_years(snapshot_ts.date(), expiration)
        if T <= 0 or iv <= 0:
            continue  # skip degenerate (F-r ant #3 0DTE handling)

        bs_input = BlackScholesInput(
            underlying_price=spot,
            strike=strike,
            time_to_expiry_years=T,
            volatility=iv,
            option_type=option_type,
            dividend_yield=dividend_yield,
            risk_free_rate=risk_free_rate,
        )

        vanna_per_contract = calculate_vanna(bs_input)
        charm_per_year = calculate_charm(bs_input)
        charm_per_day = charm_per_year / 365.0  # D-γ-7 per-day convention

        vanna_total += vanna_per_contract * oi * CONTRACT_MULTIPLIER
        charm_total += charm_per_day * oi * CONTRACT_MULTIPLIER

    return (vanna_total, charm_total)


def build_gex_snapshot(
    surface_rows: Sequence[dict],
    underlying: str,
    spot: float,
    snapshot_ts: datetime | None = None,
) -> GexSnapshot:
    """Build GexSnapshot from iv_surface rows + spot.

    Sprint 13 gex-b: vanna_total + charm_total populated via Hull canonical
    (shared_core greeks_calculator extension D-α-7).
    """
    if snapshot_ts is None:
        snapshot_ts = datetime.now(timezone.utc)

    gex_per_strike = compute_gex_per_strike(surface_rows, spot)
    gex_per_expiration = compute_gex_per_expiration(surface_rows, spot, snapshot_ts)
    gex_total = sum(gex_per_strike.values())
    gamma_flip_point = compute_gamma_flip_point(gex_per_strike)
    vanna_total, charm_total = compute_vanna_charm_totals(
        surface_rows, spot, snapshot_ts
    )

    return GexSnapshot(
        underlying=underlying,
        snapshot_at=snapshot_ts,
        spot=spot,
        gex_total=gex_total,
        gex_per_expiration=gex_per_expiration,
        gex_per_strike=gex_per_strike,
        gamma_flip_point=gamma_flip_point,
        vanna_total=vanna_total,  # Sprint 13 gex-b populated (D-α-7 Hull canonical)
        charm_total=charm_total,  # Sprint 13 gex-b populated (D-α-7 Hull canonical)
    )
