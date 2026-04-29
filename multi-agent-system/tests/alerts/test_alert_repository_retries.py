"""
Unit tests for AlertRepository retry-queue methods.
Pool is mocked — no real DB required.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, call

import pytest

from multi_agent.alerts.repository import AlertRepository


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_repo(rows=None, col_names=None):
    """Return (repo, mock_cursor) with a pool that yields a mock cursor."""
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = rows or []
    if col_names:
        mock_cur.description = [(name,) for name in col_names]
    else:
        mock_cur.description = []

    mock_pool = MagicMock()

    @contextmanager
    def _cursor():
        yield mock_cur

    mock_pool.cursor = _cursor
    return AlertRepository(mock_pool), mock_cur


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestListEligibleRetries:

    def test_returns_empty_list_when_no_rows(self):
        repo, _ = _make_repo(rows=[])
        result = repo.list_eligible_retries()
        assert result == []

    def test_query_contains_for_update_skip_locked(self):
        repo, mock_cur = _make_repo(rows=[])
        repo.list_eligible_retries()
        sql = mock_cur.execute.call_args[0][0]
        assert "FOR UPDATE SKIP LOCKED" in sql

    def test_query_filters_given_up_at_is_null(self):
        repo, mock_cur = _make_repo(rows=[])
        repo.list_eligible_retries()
        sql = mock_cur.execute.call_args[0][0]
        assert "given_up_at IS NULL" in sql

    def test_query_filters_sent_at_is_null(self):
        repo, mock_cur = _make_repo(rows=[])
        repo.list_eligible_retries()
        sql = mock_cur.execute.call_args[0][0]
        assert "sent_at IS NULL" in sql

    def test_query_branches_on_retry_count(self):
        """Query must handle all 4 retry_count variants with correct intervals."""
        repo, mock_cur = _make_repo(rows=[])
        repo.list_eligible_retries()
        sql = mock_cur.execute.call_args[0][0]
        assert "INTERVAL '30 seconds'" in sql
        assert "INTERVAL '2 minutes'" in sql
        assert "INTERVAL '5 minutes'" in sql
        assert "INTERVAL '15 minutes'" in sql

    def test_returns_dicts_with_column_names(self):
        cols = ["id", "event_type", "severity", "title"]
        rows = [(1, "system.failure", "CRITICAL", "Test")]
        repo, _ = _make_repo(rows=rows, col_names=cols)
        result = repo.list_eligible_retries()
        assert len(result) == 1
        assert result[0] == {"id": 1, "event_type": "system.failure",
                              "severity": "CRITICAL", "title": "Test"}

    def test_default_limit_is_50(self):
        repo, mock_cur = _make_repo(rows=[])
        repo.list_eligible_retries()
        params = mock_cur.execute.call_args[0][1]
        assert params == [50]

    def test_custom_limit_forwarded(self):
        repo, mock_cur = _make_repo(rows=[])
        repo.list_eligible_retries(limit=10)
        params = mock_cur.execute.call_args[0][1]
        assert params == [10]


class TestMarkRetryClaimed:

    def test_updates_last_retry_at(self):
        repo, mock_cur = _make_repo()
        repo.mark_retry_claimed(99)
        sql, params = mock_cur.execute.call_args[0]
        assert "last_retry_at" in sql
        assert "NOW()" in sql
        assert params == [99]


class TestMarkRetrySuccess:

    def test_sets_sent_at_and_sink_message_id(self):
        repo, mock_cur = _make_repo()
        repo.mark_retry_success(7, "msg-abc")
        sql, params = mock_cur.execute.call_args[0]
        assert "sent_at" in sql
        assert "sink_message_id" in sql
        assert params[0] == "msg-abc"
        assert params[1] == 7

    def test_increments_retry_count(self):
        repo, mock_cur = _make_repo()
        repo.mark_retry_success(7, "msg-abc")
        sql, _ = mock_cur.execute.call_args[0]
        assert "retry_count + 1" in sql


class TestMarkRetryFailure:

    def test_increments_retry_count_and_sets_error_msg(self):
        repo, mock_cur = _make_repo()
        repo.mark_retry_failure(5, "connection refused")
        sql, params = mock_cur.execute.call_args[0]
        assert "retry_count + 1" in sql
        assert "error_msg" in sql
        assert params[0] == "connection refused"
        assert params[1] == 5

    def test_truncates_long_error_msg(self):
        repo, mock_cur = _make_repo()
        long_msg = "x" * 600
        repo.mark_retry_failure(5, long_msg)
        params = mock_cur.execute.call_args[0][1]
        assert len(params[0]) == 512


class TestMarkGivenUp:

    def test_sets_given_up_at(self):
        repo, mock_cur = _make_repo()
        repo.mark_given_up(3, "all retries exhausted")
        sql, params = mock_cur.execute.call_args[0]
        assert "given_up_at" in sql
        assert "NOW()" in sql
        assert params[0] == "all retries exhausted"
        assert params[1] == 3

    def test_increments_retry_count(self):
        repo, mock_cur = _make_repo()
        repo.mark_given_up(3, "fail")
        sql, _ = mock_cur.execute.call_args[0]
        assert "retry_count + 1" in sql

    def test_truncates_long_error_msg(self):
        repo, mock_cur = _make_repo()
        long_msg = "e" * 700
        repo.mark_given_up(3, long_msg)
        params = mock_cur.execute.call_args[0][1]
        assert len(params[0]) == 512
