"""
LLM cost tracking decorator.

Usage:
    @track_llm_cost(
        task_type="proposal_generation",
        agent_id="athena",
        model_used="claude-sonnet-4-6",
        criticality="high",
    )
    def call_llm(..., correlation_id: UUID | None = None):
        return client.messages.create(...)

The wrapped function's return value must expose .usage with input_tokens,
cache_creation_input_tokens, cache_read_input_tokens, and output_tokens
(standard Anthropic SDK response shape). Results without .usage are silently
skipped (debug-logged only).

Tracking failures NEVER propagate — they are logged as warnings and swallowed.
The wrapped function's behavior and return value are never affected.

For tests, inject repo= to bypass DB writes:
    @track_llm_cost(..., repo=mock_repo)

correlation_id is resolved from both positional and keyword args automatically
using inspect.signature cached at decoration time.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


def track_llm_cost(
    *,
    task_type: str,
    agent_id: str,
    model_used: str,
    criticality: str = "normal",
    is_batch_api: bool = False,
    repo=None,  # LLMCostRepository | None — late import avoids circular dep
) -> Callable:
    """
    Decorator factory that records LLM token usage after each call.

    Args:
        task_type:    Matches the task_type column in analytics.llm_costs.
        agent_id:     The agent making the LLM call.
        model_used:   Model ID string (e.g. "claude-sonnet-4-6").
        criticality:  "low" | "normal" | "high" — maps to the criticality column.
        is_batch_api: True if using Anthropic Batch API (50% off input/output).
        repo:         Optional LLMCostRepository for testing. If None, created
                      lazily from the global pool on first call (production).
    """
    def decorator(fn: Callable) -> Callable:
        # Cache signature once at decoration time for positional-arg resolution.
        _sig = inspect.signature(fn)

        # Thread-safe lazy init: double-checked locking.
        # Lock acquired only on first call; thereafter _repo_cell[0] is set.
        _repo_cell: list = [repo]
        _init_lock = threading.Lock()

        def _get_repo():
            if _repo_cell[0] is None:
                with _init_lock:
                    if _repo_cell[0] is None:  # re-check inside lock
                        from shared_core.storage.postgres_pool import get_pool
                        from multi_agent.observability.llm_cost_repository import LLMCostRepository
                        _repo_cell[0] = LLMCostRepository(get_pool())
            return _repo_cell[0]

        def _resolve_correlation_id(args: tuple, kwargs: dict) -> Any:
            if "correlation_id" in kwargs:
                return kwargs["correlation_id"]
            try:
                bound = _sig.bind_partial(*args, **kwargs)
                return bound.arguments.get("correlation_id")
            except TypeError:
                return None

        def _record(result: Any, args: tuple, kwargs: dict) -> None:
            try:
                usage = _extract_usage(result)
                if usage is None:
                    return
                corr_id = _resolve_correlation_id(args, kwargs)
                _get_repo().log(
                    agent_id=agent_id,
                    task_type=task_type,
                    model_used=model_used,
                    criticality=criticality,
                    is_batch_api=is_batch_api,
                    correlation_id=corr_id,
                    **usage,
                )
            except Exception:
                logger.warning(
                    "track_llm_cost: failed to record — agent=%s task=%s",
                    agent_id, task_type,
                    exc_info=True,
                )

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = fn(*args, **kwargs)
            _record(result, args, kwargs)
            return result

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await fn(*args, **kwargs)
            _record(result, args, kwargs)
            return result

        return async_wrapper if inspect.iscoroutinefunction(fn) else sync_wrapper

    return decorator


def _extract_usage(result: Any) -> dict[str, int] | None:
    """
    Extract token counts from an Anthropic SDK response.

    Returns None if result has no .usage attribute (not an LLM response).
    Tracks four token types: input, cache_creation, cache_read, output.
    Missing sub-fields default to 0.
    """
    usage = getattr(result, "usage", None)
    if usage is None:
        logger.debug("track_llm_cost: result has no .usage — skipping")
        return None
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "cache_creation_input_tokens": int(
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        ),
        "cached_input_tokens": int(
            getattr(usage, "cache_read_input_tokens", 0) or 0
        ),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }
