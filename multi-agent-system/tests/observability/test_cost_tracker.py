"""
Unit tests for track_llm_cost decorator.
No DB required — all tests use a mock repo.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, call
from uuid import UUID, uuid4

import pytest

from multi_agent.observability.cost_tracker import _extract_usage, track_llm_cost


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_usage(
    input_tokens=100,
    cache_creation_input_tokens=0,
    cache_read_input_tokens=0,
    output_tokens=50,
):
    u = MagicMock()
    u.input_tokens = input_tokens
    u.cache_creation_input_tokens = cache_creation_input_tokens
    u.cache_read_input_tokens = cache_read_input_tokens
    u.output_tokens = output_tokens
    return u


def _make_response(**kwargs):
    r = MagicMock()
    r.usage = _make_usage(**kwargs)
    return r


# ── _extract_usage ────────────────────────────────────────────────────────────

class TestExtractUsage:

    def test_returns_none_when_no_usage_attr(self):
        result = MagicMock(spec=[])  # no .usage
        assert _extract_usage(result) is None

    def test_extracts_four_token_types(self):
        resp = _make_response(
            input_tokens=1000,
            cache_creation_input_tokens=200,
            cache_read_input_tokens=800,
            output_tokens=300,
        )
        usage = _extract_usage(resp)
        assert usage == {
            "input_tokens": 1000,
            "cache_creation_input_tokens": 200,
            "cached_input_tokens": 800,
            "output_tokens": 300,
        }

    def test_missing_subfields_default_to_zero(self):
        usage_obj = MagicMock(spec=["input_tokens", "output_tokens"])
        usage_obj.input_tokens = 500
        usage_obj.output_tokens = 100
        resp = MagicMock()
        resp.usage = usage_obj
        result = _extract_usage(resp)
        assert result["cache_creation_input_tokens"] == 0
        assert result["cached_input_tokens"] == 0


# ── track_llm_cost — sync ─────────────────────────────────────────────────────

class TestTrackLlmCostSync:

    def _decorated(self, repo):
        @track_llm_cost(
            task_type="proposal_generation",
            agent_id="athena",
            model_used="claude-sonnet-4-6",
            criticality="high",
            repo=repo,
        )
        def call_llm(prompt, correlation_id=None):
            return _make_response(input_tokens=100, output_tokens=50)

        return call_llm

    def test_does_not_alter_return_value(self):
        repo = MagicMock()
        fn = self._decorated(repo)
        result = fn("hello")
        assert result is not None
        assert hasattr(result, "usage")

    def test_calls_repo_log_with_correct_params(self):
        repo = MagicMock()
        fn = self._decorated(repo)
        corr = uuid4()
        fn("hello", correlation_id=corr)

        repo.log.assert_called_once()
        kwargs = repo.log.call_args.kwargs
        assert kwargs["agent_id"] == "athena"
        assert kwargs["task_type"] == "proposal_generation"
        assert kwargs["model_used"] == "claude-sonnet-4-6"
        assert kwargs["criticality"] == "high"
        assert kwargs["input_tokens"] == 100
        assert kwargs["output_tokens"] == 50
        assert kwargs["correlation_id"] == corr

    def test_correlation_id_from_positional_arg(self):
        """correlation_id passed as positional must be captured."""
        repo = MagicMock()

        @track_llm_cost(
            task_type="t", agent_id="a", model_used="claude-sonnet-4-6", repo=repo
        )
        def fn(prompt, correlation_id=None):
            return _make_response()

        corr = uuid4()
        fn("hello", corr)  # positional — not keyword
        kwargs = repo.log.call_args.kwargs
        assert kwargs["correlation_id"] == corr

    def test_does_not_propagate_repo_exception(self):
        """Repo error must be swallowed — never surface to caller."""
        repo = MagicMock()
        repo.log.side_effect = RuntimeError("db down")
        fn = self._decorated(repo)
        # Must not raise
        result = fn("hello")
        assert result is not None

    def test_preserves_function_name(self):
        repo = MagicMock()
        fn = self._decorated(repo)
        assert fn.__name__ == "call_llm"

    def test_is_batch_api_passed_to_repo(self):
        repo = MagicMock()

        @track_llm_cost(
            task_type="t", agent_id="a", model_used="claude-sonnet-4-6",
            is_batch_api=True, repo=repo,
        )
        def fn():
            return _make_response()

        fn()
        assert repo.log.call_args.kwargs["is_batch_api"] is True


# ── track_llm_cost — async ────────────────────────────────────────────────────

class TestTrackLlmCostAsync:

    def test_async_function_decorated_correctly(self):
        repo = MagicMock()

        @track_llm_cost(
            task_type="t", agent_id="a", model_used="claude-sonnet-4-6", repo=repo
        )
        async def async_fn():
            return _make_response(input_tokens=200, output_tokens=80)

        asyncio.run(async_fn())
        repo.log.assert_called_once()
        kwargs = repo.log.call_args.kwargs
        assert kwargs["input_tokens"] == 200
        assert kwargs["output_tokens"] == 80

    def test_cache_tokens_tracked_in_async(self):
        repo = MagicMock()

        @track_llm_cost(
            task_type="t", agent_id="a", model_used="claude-sonnet-4-6", repo=repo
        )
        async def async_fn():
            return _make_response(
                input_tokens=1000,
                cache_creation_input_tokens=200,
                cache_read_input_tokens=800,
                output_tokens=300,
            )

        asyncio.run(async_fn())
        kwargs = repo.log.call_args.kwargs
        assert kwargs["cache_creation_input_tokens"] == 200
        assert kwargs["cached_input_tokens"] == 800
