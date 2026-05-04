"""
Unit tests for LLMCostRepository.
No real DB — pool and cursor are mocked.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import yaml

from multi_agent.observability.llm_cost_repository import LLMCostRepository, _coerce_uuid


# ── Fixtures ──────────────────────────────────────────────────────────────────

PRICING_DATA = {
    "models": {
        "claude-sonnet-4-6": {
            "input_per_million": 3.00,
            "cache_creation_per_million": 3.75,
            "cached_input_per_million": 0.30,
            "output_per_million": 15.00,
            "batch": {
                "input_per_million": 1.50,
                "output_per_million": 7.50,
            },
        },
        "claude-opus-4-7": {
            "input_per_million": 5.00,
            "cache_creation_per_million": 6.25,
            "cached_input_per_million": 0.50,
            "output_per_million": 25.00,
            "batch": {
                "input_per_million": 2.50,
                "output_per_million": 12.50,
            },
        },
        "claude-haiku-4-5-20251001": {
            "input_per_million": 1.00,
            "cache_creation_per_million": 1.25,
            "cached_input_per_million": 0.10,
            "output_per_million": 5.00,
            "batch": {
                "input_per_million": 0.50,
                "output_per_million": 2.50,
            },
        },
    }
}


@pytest.fixture
def pricing_file(tmp_path) -> Path:
    p = tmp_path / "llm_pricing.yaml"
    p.write_text(yaml.dump(PRICING_DATA))
    return p


def _make_pool_and_cursor():
    """Return (pool, mock_cursor) with pool.cursor() wired up."""
    mock_cursor = MagicMock()
    mock_cursor.__enter__ = lambda s: mock_cursor
    mock_cursor.__exit__ = MagicMock(return_value=False)

    mock_pool = MagicMock()

    @contextmanager
    def fake_cursor():
        yield mock_cursor

    mock_pool.cursor = fake_cursor
    return mock_pool, mock_cursor


@pytest.fixture
def repo(pricing_file):
    pool, _ = _make_pool_and_cursor()
    return LLMCostRepository(pool, pricing_path=pricing_file)


# ── _coerce_uuid ──────────────────────────────────────────────────────────────

class TestCoerceUuid:

    def test_none_returns_none(self):
        assert _coerce_uuid(None) is None

    def test_uuid_passthrough(self):
        u = uuid4()
        assert _coerce_uuid(u) is u

    def test_string_uuid_converts(self):
        u = uuid4()
        result = _coerce_uuid(str(u))
        assert result == u

    def test_invalid_string_returns_none(self):
        assert _coerce_uuid("not-a-uuid") is None


# ── Cost calculation ──────────────────────────────────────────────────────────

class TestCalculateCost:

    def test_sonnet_standard_cost(self, repo):
        cost = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=1_000_000,
            cache_creation_input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            is_batch_api=False,
        )
        assert abs(cost - 3.00) < 1e-6

    def test_sonnet_output_cost(self, repo):
        cost = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=0,
            cache_creation_input_tokens=0,
            cached_input_tokens=0,
            output_tokens=1_000_000,
            is_batch_api=False,
        )
        assert abs(cost - 15.00) < 1e-6

    def test_cache_creation_more_expensive_than_input(self, repo):
        """cache_creation_per_million (3.75) > input_per_million (3.00) for sonnet."""
        cost_input = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=1_000_000,
            cache_creation_input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            is_batch_api=False,
        )
        cost_creation = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=0,
            cache_creation_input_tokens=1_000_000,
            cached_input_tokens=0,
            output_tokens=0,
            is_batch_api=False,
        )
        assert cost_creation > cost_input

    def test_cache_read_cheaper_than_input(self, repo):
        """cached_input_per_million (0.30) < input_per_million (3.00) for sonnet."""
        cost_input = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=1_000_000,
            cache_creation_input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            is_batch_api=False,
        )
        cost_read = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=0,
            cache_creation_input_tokens=0,
            cached_input_tokens=1_000_000,
            output_tokens=0,
            is_batch_api=False,
        )
        assert cost_read < cost_input

    def test_batch_api_halves_input_and_output(self, repo):
        standard = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=1_000_000,
            cache_creation_input_tokens=0,
            cached_input_tokens=0,
            output_tokens=1_000_000,
            is_batch_api=False,
        )
        batch = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=1_000_000,
            cache_creation_input_tokens=0,
            cached_input_tokens=0,
            output_tokens=1_000_000,
            is_batch_api=True,
        )
        assert abs(batch - standard / 2) < 1e-6

    def test_batch_does_not_discount_cache_creation(self, repo):
        """Cache creation rate is the same for batch and standard."""
        standard_cc = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=0,
            cache_creation_input_tokens=1_000_000,
            cached_input_tokens=0,
            output_tokens=0,
            is_batch_api=False,
        )
        batch_cc = repo._calculate_cost(
            model_used="claude-sonnet-4-6",
            input_tokens=0,
            cache_creation_input_tokens=1_000_000,
            cached_input_tokens=0,
            output_tokens=0,
            is_batch_api=True,
        )
        assert abs(standard_cc - batch_cc) < 1e-9

    def test_unknown_model_returns_zero_with_warning(self, repo, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            cost = repo._calculate_cost(
                model_used="gpt-4o",
                input_tokens=1_000_000,
                cache_creation_input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                is_batch_api=False,
            )
        assert cost == 0.0
        assert "unknown model" in caplog.text.lower() or "gpt-4o" in caplog.text


# ── log() — insert ────────────────────────────────────────────────────────────

class TestLog:

    def test_log_executes_insert(self, pricing_file):
        pool, cursor = _make_pool_and_cursor()
        r = LLMCostRepository(pool, pricing_path=pricing_file)
        r.log(
            agent_id="athena",
            task_type="proposal_generation",
            model_used="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=200,
        )
        cursor.execute.assert_called_once()
        sql = cursor.execute.call_args.args[0]
        assert "INSERT INTO analytics.llm_costs" in sql

    def test_log_passes_cost_usd_to_execute(self, pricing_file):
        pool, cursor = _make_pool_and_cursor()
        r = LLMCostRepository(pool, pricing_path=pricing_file)
        r.log(
            agent_id="athena",
            task_type="t",
            model_used="claude-sonnet-4-6",
            input_tokens=1_000_000,
            output_tokens=0,
        )
        params = cursor.execute.call_args.args[1]
        cost_usd = params[7]  # 8th param in the INSERT
        assert abs(cost_usd - 3.0) < 1e-4

    def test_log_passes_cache_creation_tokens(self, pricing_file):
        pool, cursor = _make_pool_and_cursor()
        r = LLMCostRepository(pool, pricing_path=pricing_file)
        r.log(
            agent_id="athena",
            task_type="t",
            model_used="claude-sonnet-4-6",
            input_tokens=0,
            cache_creation_input_tokens=500,
            cached_input_tokens=200,
            output_tokens=0,
        )
        params = cursor.execute.call_args.args[1]
        assert params[4] == 500  # cache_creation_input_tokens
        assert params[5] == 200  # cached_input_tokens


# ── Aggregation reads ─────────────────────────────────────────────────────────

class TestAggregationReads:

    def _repo_with_rows(self, pricing_file, rows, description=None):
        """Return a repo whose cursor.fetchall() returns the given rows."""
        pool, cursor = _make_pool_and_cursor()
        cursor.fetchall.return_value = rows
        if description:
            cursor.description = [(col,) for col in description]
        return LLMCostRepository(pool, pricing_path=pricing_file)

    def test_get_summary_empty_returns_zeros(self, pricing_file):
        r = self._repo_with_rows(pricing_file, [])
        summary = r.get_summary_by_period(days=7)
        assert summary["total_cost_usd"] == 0.0
        assert summary["total_calls"] == 0
        assert summary["by_model"] == []

    def test_get_summary_aggregates_correctly(self, pricing_file):
        rows = [
            ("claude-sonnet-4-6", 10, 0.045, 5000),
            ("claude-haiku-4-5-20251001", 5, 0.010, 2000),
        ]
        r = self._repo_with_rows(pricing_file, rows)
        summary = r.get_summary_by_period(days=7)
        assert abs(summary["total_cost_usd"] - 0.055) < 1e-9
        assert summary["total_calls"] == 15
        assert len(summary["by_model"]) == 2

    def test_get_daily_totals_returns_date_strings(self, pricing_file):
        import datetime
        rows = [(datetime.date(2026, 4, 28), 3, 0.01, 1000)]
        r = self._repo_with_rows(pricing_file, rows)
        daily = r.get_daily_totals(days=7)
        assert daily[0].date == "2026-04-28"
        assert daily[0].calls == 3
