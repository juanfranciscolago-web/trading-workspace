"""GEX compute pipeline — Tier A signal generation (ADR-011, Sprint 13)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Sequence

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


def build_gex_snapshot(
    surface_rows: Sequence[dict],
    underlying: str,
    spot: float,
    snapshot_ts: datetime | None = None,
) -> GexSnapshot:
    """Build GexSnapshot from iv_surface rows + spot.

    Sprint 13 gex-a scaffold: vanna_total + charm_total init 0.0.
    Sprint 13 gex-b populates via shared_core greeks_calculator extension.
    """
    if snapshot_ts is None:
        snapshot_ts = datetime.now(timezone.utc)

    gex_per_strike = compute_gex_per_strike(surface_rows, spot)
    gex_per_expiration = compute_gex_per_expiration(surface_rows, spot, snapshot_ts)
    gex_total = sum(gex_per_strike.values())
    gamma_flip_point = compute_gamma_flip_point(gex_per_strike)

    return GexSnapshot(
        underlying=underlying,
        snapshot_at=snapshot_ts,
        spot=spot,
        gex_total=gex_total,
        gex_per_expiration=gex_per_expiration,
        gex_per_strike=gex_per_strike,
        gamma_flip_point=gamma_flip_point,
        vanna_total=0.0,  # Sprint 13 gex-b populated (D-ε-6)
        charm_total=0.0,  # Sprint 13 gex-b populated (D-ε-6)
    )
