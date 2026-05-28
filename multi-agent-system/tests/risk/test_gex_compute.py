"""Tests for GEX compute pipeline (Sprint 13 gex-a, ADR-011).

D1-D10 implementation verification: 4 aggregation levels + GexSnapshot
scaffold + Vanna/Charm init 0.0 (Sprint 13 gex-b populated).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from multi_agent.risk.gex_compute import (
    CONTRACT_MULTIPLIER,
    DTE_BUCKETS,
    GexSnapshot,
    _bucket_for_dte,
    _dte_from_expiration,
    build_gex_snapshot,
    compute_gamma_flip_point,
    compute_gex_per_expiration,
    compute_gex_per_strike,
    compute_vanna_charm_totals,
)


def _row(strike: float, gamma: float, oi: int, option_type: str,
         expiration: date | None = None, iv: float = 0.20) -> dict:
    """Synthetic iv_surface row factory (iv field added Sprint 13 gex-b)."""
    return {
        "strike": strike,
        "gamma": gamma,
        "open_interest": oi,
        "option_type": option_type,
        "iv": iv,
        "expiration": expiration or date(2026, 6, 20),
    }


class TestDTEBuckets:
    """DTE bucket mapping per ADR-011 D5."""

    def test_0dte_bucket(self):
        assert _bucket_for_dte(0) == "0DTE"

    def test_intermediate_buckets(self):
        assert _bucket_for_dte(15) == "8-30DTE"
        assert _bucket_for_dte(45) == "31-60DTE"
        assert _bucket_for_dte(100) == ">60DTE"

    def test_dte_from_expiration(self):
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        expiration = date(2026, 6, 27)
        assert _dte_from_expiration(expiration, ts) == 30


class TestComputeGexPerStrike:
    """GEX per-strike formula per ADR-011 D4."""

    def test_single_strike_call(self):
        """Single CALL strike → positive GEX contribution."""
        rows = [_row(strike=100.0, gamma=0.05, oi=1000, option_type="CALL")]
        spot = 100.0
        result = compute_gex_per_strike(rows, spot)

        # Expected: 1 * 0.05 * 1000 * 100*100 * 0.01 * 100 = 500,000
        expected = 0.05 * 1000 * (100.0 ** 2) * 0.01 * CONTRACT_MULTIPLIER
        assert result[100.0] == pytest.approx(expected)
        assert result[100.0] > 0

    def test_single_strike_put_negative_sign(self):
        """PUT strike → negative GEX contribution per D4."""
        rows = [_row(strike=100.0, gamma=0.05, oi=1000, option_type="PUT")]
        spot = 100.0
        result = compute_gex_per_strike(rows, spot)

        assert result[100.0] < 0

    def test_multiple_strikes_aggregation(self):
        """Multiple strikes aggregate distinct keys."""
        rows = [
            _row(100.0, 0.05, 1000, "CALL"),
            _row(105.0, 0.04, 500, "CALL"),
        ]
        result = compute_gex_per_strike(rows, 100.0)
        assert len(result) == 2
        assert 100.0 in result
        assert 105.0 in result

    def test_invalid_spot_returns_empty(self):
        """spot=0 → empty dict (F-r ant #7 defensive)."""
        rows = [_row(100.0, 0.05, 1000, "CALL")]
        result = compute_gex_per_strike(rows, 0.0)
        assert result == {}


class TestComputeGexPerExpiration:
    """GEX per-expiration DTE-bucketed per ADR-011 D5."""

    def test_single_expiration_bucketed(self):
        """Single expiration → bucket correctly assigned."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [_row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 5))]
        # DTE = 8 days → "8-30DTE" bucket
        result = compute_gex_per_expiration(rows, 100.0, ts)
        assert result["8-30DTE"] > 0
        assert result["0DTE"] == 0.0

    def test_multiple_expirations_distinct_buckets(self):
        """Multiple expirations → distinct buckets populated."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 5, 28)),  # 0DTE
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 28)),  # 31-60DTE
        ]
        result = compute_gex_per_expiration(rows, 100.0, ts)
        assert result["0DTE"] > 0
        assert result["31-60DTE"] > 0

    def test_empty_input(self):
        """Empty rows → all buckets 0.0."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        result = compute_gex_per_expiration([], 100.0, ts)
        assert all(v == 0.0 for v in result.values())


class TestGammaFlipPoint:
    """Gamma flip point detection per ADR-011 D5."""

    def test_flip_detected_positive_to_negative(self):
        """Cumulative goes positive→negative → flip strike detected."""
        gex_per_strike = {90.0: 100.0, 95.0: 50.0, 100.0: -200.0, 105.0: -50.0}
        result = compute_gamma_flip_point(gex_per_strike)
        assert result == 100.0  # cumulative becomes negative at 100

    def test_no_flip_all_positive(self):
        """All strikes positive → no flip (None)."""
        gex_per_strike = {90.0: 100.0, 95.0: 50.0, 100.0: 200.0}
        result = compute_gamma_flip_point(gex_per_strike)
        assert result is None

    def test_empty_dict_returns_none(self):
        """Empty input → None."""
        result = compute_gamma_flip_point({})
        assert result is None


class TestBuildGexSnapshot:
    """GexSnapshot integration per ADR-011 D8."""

    def test_full_synthetic_snapshot(self):
        """Full GexSnapshot from synthetic rows."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 5)),
            _row(100.0, 0.03, 500, "PUT", expiration=date(2026, 6, 5)),
        ]
        snapshot = build_gex_snapshot(rows, "SPY", 100.0, snapshot_ts=ts)

        assert snapshot.underlying == "SPY"
        assert snapshot.spot == 100.0
        assert snapshot.snapshot_at == ts
        assert 100.0 in snapshot.gex_per_strike
        assert snapshot.gex_total != 0.0

    def test_vanna_charm_populated_gex_b(self):
        """Sprint 13 gex-b: vanna/charm populated via Hull canonical (D-α-7).

        D-η-7: renamed from test_vanna_charm_init_zero_gex_a_scaffold.
        Gex-a scaffold returned 0.0; gex-b populates via shared_core
        greeks_calculator extension. With non-degenerate inputs (T>0, iv>0),
        vanna/charm are non-zero floats.
        """
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [_row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 27))]
        snapshot = build_gex_snapshot(rows, "SPY", 100.0, snapshot_ts=ts)

        assert isinstance(snapshot.vanna_total, float)
        assert isinstance(snapshot.charm_total, float)
        # ATM call ~30 DTE has some non-zero charm (delta decay)
        assert snapshot.charm_total != 0.0


class TestComputeVannaCharmTotals:
    """Aggregate Vanna/Charm per ADR-011 D6 amendment Sprint 13 gex-b."""

    def test_basic_aggregation(self):
        """Multiple strikes aggregate weighted by OI."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 27)),
            _row(105.0, 0.03, 500, "CALL", expiration=date(2026, 6, 27)),
        ]
        vanna, charm = compute_vanna_charm_totals(rows, 100.0, ts)
        assert isinstance(vanna, float)
        assert isinstance(charm, float)

    def test_case_translation_uppercase(self):
        """option_type 'CALL'/'PUT' uppercase translates to lowercase (F-r ant #1)."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [_row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 27))]
        vanna, charm = compute_vanna_charm_totals(rows, 100.0, ts)
        assert isinstance(vanna, float)

    def test_zero_dte_skipped(self):
        """T<=0 (0DTE same-day) skipped defensively."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [_row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 5, 28))]
        vanna, charm = compute_vanna_charm_totals(rows, 100.0, ts)
        assert vanna == 0.0
        assert charm == 0.0

    def test_invalid_spot_returns_zeros(self):
        """spot<=0 → (0.0, 0.0) defensive."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [_row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 27))]
        vanna, charm = compute_vanna_charm_totals(rows, 0.0, ts)
        assert vanna == 0.0
        assert charm == 0.0

    def test_default_snapshot_ts_utc(self):
        """snapshot_ts defaults to datetime.now(UTC)."""
        rows = [_row(100.0, 0.05, 1000, "CALL")]
        snapshot = build_gex_snapshot(rows, "SPY", 100.0)

        assert snapshot.snapshot_at.tzinfo is not None


class TestIvSurfaceIntegration:
    """R1 mitigation: mocked IvSurfaceRepository integration."""

    def test_mocked_repo_to_gex_snapshot_integration(self):
        """Full path: mocked iv_surface_repo → build_gex_snapshot."""
        mock_repo = MagicMock()
        mock_rows = [
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 27)),
            _row(105.0, 0.03, 500, "CALL", expiration=date(2026, 6, 27)),
            _row(95.0, 0.04, 800, "PUT", expiration=date(2026, 6, 27)),
        ]
        mock_repo.get_surface_for_ticker.return_value = mock_rows

        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        surface_rows = mock_repo.get_surface_for_ticker("SPY", ts)
        snapshot = build_gex_snapshot(surface_rows, "SPY", 100.0, snapshot_ts=ts)

        mock_repo.get_surface_for_ticker.assert_called_once_with("SPY", ts)
        assert snapshot.underlying == "SPY"
        assert len(snapshot.gex_per_strike) >= 1


class TestEndToEndIntegration:
    """End-to-end integration tests Sprint 13 gex-c (ADR-011 D7)."""

    def test_realistic_multi_strike_multi_expiration(self):
        """20-strike × 3-expiration synthetic distribution → GexSnapshot shape."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        spot = 100.0
        expirations = [date(2026, 6, 5), date(2026, 6, 27), date(2026, 8, 15)]
        rows = []
        for exp in expirations:
            for strike_offset in range(-10, 11):
                strike = spot + strike_offset
                gamma = 0.05 * (1 - abs(strike_offset) / 15.0)  # ATM peak distribution
                for opt_type in ["CALL", "PUT"]:
                    rows.append(_row(strike, gamma, 500, opt_type, expiration=exp))

        snapshot = build_gex_snapshot(rows, "SPY", spot, snapshot_ts=ts)

        assert snapshot.underlying == "SPY"
        assert snapshot.spot == spot
        assert len(snapshot.gex_per_strike) >= 15
        assert len(snapshot.gex_per_expiration) == 5  # 5 DTE buckets defined
        # Sum buckets should equal gex_total (within float precision)
        assert abs(sum(snapshot.gex_per_expiration.values()) - snapshot.gex_total) < 1.0

    def test_hand_computed_atm_call_benchmark(self):
        """ATM 30-DTE call known input → hand-computed gex_total within 5% tolerance.

        Hull textbook reference: SPY @ $100, ATM call $100 strike, 30-DTE, σ=20%, OI=10000.
        gamma ≈ 0.06 (approximate ATM 30-DTE).
        Expected GEX_per_strike: 1 × 0.06 × 10000 × 100² × 0.01 × 100 = 600,000.
        """
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [_row(100.0, 0.06, 10000, "CALL", expiration=date(2026, 6, 27))]
        snapshot = build_gex_snapshot(rows, "SPY", 100.0, snapshot_ts=ts)

        expected = 0.06 * 10000 * (100.0 ** 2) * 0.01 * CONTRACT_MULTIPLIER
        tolerance = expected * 0.05
        assert abs(snapshot.gex_total - expected) < tolerance

    def test_empty_surface_degenerate(self):
        """Empty rows → snapshot zeros + gamma_flip_point None."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        snapshot = build_gex_snapshot([], "SPY", 100.0, snapshot_ts=ts)

        assert snapshot.gex_total == 0.0
        assert snapshot.gex_per_strike == {}
        assert snapshot.gamma_flip_point is None
        assert snapshot.vanna_total == 0.0
        assert snapshot.charm_total == 0.0

    def test_extreme_iv_handling(self):
        """IV=5% (low) y IV=100% (high) → both produce non-degenerate non-zero values."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows_low = [_row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 27), iv=0.05)]
        rows_high = [_row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 27), iv=1.00)]

        snap_low = build_gex_snapshot(rows_low, "SPY", 100.0, snapshot_ts=ts)
        snap_high = build_gex_snapshot(rows_high, "SPY", 100.0, snapshot_ts=ts)

        # Both GEX values should be computed (gamma × OI × spot²)
        assert snap_low.gex_total != 0.0
        assert snap_high.gex_total != 0.0
        # Vanna/Charm should differ based on IV input
        assert (snap_low.vanna_total != snap_high.vanna_total
                or snap_low.charm_total != snap_high.charm_total)

    def test_dte_boundary_edge_cases(self):
        """DTE boundary strikes (7/30/60) → correct bucket assignment (D-β-8 Alternativa A)."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        # 7-DTE → "1-7DTE", 8-DTE → "8-30DTE", 30-DTE → "8-30DTE",
        # 31-DTE → "31-60DTE", 60-DTE → "31-60DTE", 61-DTE → ">60DTE"
        rows = [
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 4)),   # 7 DTE
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 5)),   # 8 DTE
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 27)),  # 30 DTE
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 6, 28)),  # 31 DTE
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 7, 27)),  # 60 DTE
            _row(100.0, 0.05, 1000, "CALL", expiration=date(2026, 7, 28)),  # 61 DTE
        ]
        snapshot = build_gex_snapshot(rows, "SPY", 100.0, snapshot_ts=ts)

        assert snapshot.gex_per_expiration["1-7DTE"] > 0    # 7-DTE row
        assert snapshot.gex_per_expiration["8-30DTE"] > 0   # 8-DTE + 30-DTE
        assert snapshot.gex_per_expiration["31-60DTE"] > 0  # 31-DTE + 60-DTE
        assert snapshot.gex_per_expiration[">60DTE"] > 0    # 61-DTE
