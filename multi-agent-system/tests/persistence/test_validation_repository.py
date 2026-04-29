"""
Unit tests for ValidationRepository.
No DB — pool and cursor are mocked via MagicMock.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from multi_agent.persistence.validation_repository import ValidationRepository


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pool(rows=None, cols=None):
    """Return a mock pool whose cursor() yields a mock cursor with given rows."""
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = rows or []
    mock_cur.fetchone.return_value = rows[0] if rows else None
    mock_cur.description = [(c,) for c in (cols or [])]

    mock_pool = MagicMock()
    mock_pool.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_pool.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return mock_pool, mock_cur


SAMPLE_COLS = [
    "correlation_id", "approved", "executed_size_pct", "original_size_pct",
    "reason", "atlas_version", "portfolio_snapshot_id", "evaluation_time_ms",
    "checks_passed", "checks_failed", "risk_mode", "created_at",
]

SAMPLE_ROW = (
    "abc-123", True, 5.0, 5.0, "approved:ok",
    "atlas-1.0", "a" * 64, 1.5,
    ["pnl_ok", "bp_ok"], [], "GREEN",
    datetime(2026, 4, 29, 14, 0, tzinfo=timezone.utc),
)

DETAIL_COLS = SAMPLE_COLS[:10] + ["metrics_snapshot"] + SAMPLE_COLS[10:]
DETAIL_ROW = SAMPLE_ROW[:10] + ({"nav": 1000000},) + SAMPLE_ROW[10:]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestListValidations:

    def test_returns_list(self):
        pool, _ = _make_pool(rows=[SAMPLE_ROW], cols=SAMPLE_COLS)
        repo = ValidationRepository(pool)
        result = repo.list_validations()
        assert isinstance(result, list)

    def test_empty_db_returns_empty_list(self):
        pool, _ = _make_pool(rows=[], cols=[])
        repo = ValidationRepository(pool)
        assert repo.list_validations() == []

    def test_approved_none_uses_no_approved_filter(self):
        """approved=None → SQL has no approved= clause; only (since, limit) params."""
        pool, cur = _make_pool(rows=[], cols=[])
        repo = ValidationRepository(pool)
        repo.list_validations(approved=None)
        call_args = cur.execute.call_args[0][1]
        # Branch for approved=None passes only (since, limit) — no bool param
        assert len(call_args) == 2

    def test_approved_true_passes_true_as_first_param(self):
        pool, cur = _make_pool(rows=[], cols=[])
        repo = ValidationRepository(pool)
        repo.list_validations(approved=True)
        call_args = cur.execute.call_args[0][1]
        assert call_args[0] is True

    def test_approved_false_passes_false_as_first_param(self):
        pool, cur = _make_pool(rows=[], cols=[])
        repo = ValidationRepository(pool)
        repo.list_validations(approved=False)
        call_args = cur.execute.call_args[0][1]
        assert call_args[0] is False

    def test_row_maps_to_dict_with_correct_keys(self):
        pool, _ = _make_pool(rows=[SAMPLE_ROW], cols=SAMPLE_COLS)
        repo = ValidationRepository(pool)
        result = repo.list_validations()
        assert len(result) == 1
        assert result[0]["correlation_id"] == "abc-123"
        assert result[0]["approved"] is True
        assert result[0]["risk_mode"] == "GREEN"


class TestGetByCorrelationId:

    def test_returns_dict_when_found(self):
        pool, _ = _make_pool(rows=[DETAIL_ROW], cols=DETAIL_COLS)
        repo = ValidationRepository(pool)
        result = repo.get_by_correlation_id("abc-123")
        assert isinstance(result, dict)
        assert result["correlation_id"] == "abc-123"

    def test_returns_none_when_not_found(self):
        pool, _ = _make_pool(rows=[], cols=[])
        repo = ValidationRepository(pool)
        result = repo.get_by_correlation_id("nonexistent")
        assert result is None

    def test_accepts_uuid_object(self):
        """UUID objects must be coerced to str before being passed to psycopg3."""
        uid = uuid4()
        pool, cur = _make_pool(rows=[], cols=[])
        repo = ValidationRepository(pool)
        repo.get_by_correlation_id(uid)
        call_args = cur.execute.call_args[0][1]
        assert isinstance(call_args[0], str)
        assert call_args[0] == str(uid)
