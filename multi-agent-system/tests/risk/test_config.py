"""Tests for ATLAS config loading (limits.yaml + buckets.yaml)."""
from __future__ import annotations

import pytest

from multi_agent.risk.config import (
    BucketConfig,
    Phase1Limits,
    load_buckets,
    load_limits,
    reload_config,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    reload_config()
    yield
    reload_config()


class TestLimitsLoading:
    def test_loads_without_error(self):
        limits = load_limits()
        assert isinstance(limits, Phase1Limits)

    def test_phase_is_one(self):
        assert load_limits().phase == 1

    def test_pnl_daily_halt_is_negative(self):
        assert load_limits().pnl.daily_halt_pct < 0

    def test_pnl_kill_switch_more_severe_than_halt(self):
        limits = load_limits()
        assert limits.pnl.drawdown_kill_switch_pct < limits.pnl.drawdown_halt_pct

    def test_single_name_limit_less_than_sector(self):
        limits = load_limits()
        assert limits.exposure.single_name_max_pct < limits.exposure.sector_max_pct

    def test_sector_limit_less_than_bucket(self):
        limits = load_limits()
        assert limits.exposure.sector_max_pct < limits.exposure.bucket_max_pct

    def test_beta_range_valid(self):
        limits = load_limits()
        assert limits.exposure.beta_min < 0
        assert limits.exposure.beta_max > 0

    def test_frozen_model(self):
        limits = load_limits()
        with pytest.raises(Exception):
            limits.phase = 2  # type: ignore


class TestBucketsLoading:
    def test_loads_without_error(self):
        buckets = load_buckets()
        assert isinstance(buckets, BucketConfig)

    def test_has_expected_buckets(self):
        buckets = load_buckets()
        expected = {"tech_mega_cap", "semis", "crypto_correlated", "energy", "defensives", "broad_market", "other"}
        assert expected.issubset(set(buckets.buckets))

    def test_msft_in_tech_mega_cap(self):
        assert load_buckets().bucket_for("MSFT") == "tech_mega_cap"

    def test_nvda_in_semis(self):
        assert load_buckets().bucket_for("NVDA") == "semis"

    def test_gld_in_defensives(self):
        assert load_buckets().bucket_for("GLD") == "defensives"

    def test_unknown_ticker_returns_other(self):
        assert load_buckets().bucket_for("ZZZZ_UNKNOWN") == "other"

    def test_case_insensitive_lookup(self):
        assert load_buckets().bucket_for("msft") == "tech_mega_cap"
        assert load_buckets().bucket_for("MSFT") == "tech_mega_cap"

    def test_tickers_in_bucket_returns_frozenset(self):
        tickers = load_buckets().tickers_in_bucket("tech_mega_cap")
        assert isinstance(tickers, frozenset)
        assert "MSFT" in tickers
