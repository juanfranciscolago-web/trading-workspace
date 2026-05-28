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
)


def _row(strike: float, gamma: float, oi: int, option_type: str,
         expiration: date | None = None) -> dict:
    """Synthetic iv_surface row factory."""
    return {
        "strike": strike,
        "gamma": gamma,
        "open_interest": oi,
        "option_type": option_type,
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

    def test_vanna_charm_init_zero_gex_a_scaffold(self):
        """Sprint 13 gex-a scaffold: vanna/charm = 0.0 (D-ε-6)."""
        ts = datetime(2026, 5, 28, tzinfo=timezone.utc)
        rows = [_row(100.0, 0.05, 1000, "CALL")]
        snapshot = build_gex_snapshot(rows, "SPY", 100.0, snapshot_ts=ts)

        assert snapshot.vanna_total == 0.0
        assert snapshot.charm_total == 0.0

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
