"""
Unit tests for SystemRepository.
No DB — pool and cursor are mocked via MagicMock.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from multi_agent.persistence.system_repository import SystemRepository


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


_NOW = datetime(2026, 5, 8, 18, 30, tzinfo=timezone.utc)
_GET_COLS = ["mode", "changed_at", "source", "actor"]
_INSERT_COLS = ["mode", "changed_at", "source"]


# ── get_current_mode ──────────────────────────────────────────────────────────

class TestGetCurrentMode:

    def test_returns_none_when_table_empty(self):
        pool, _ = _make_pool(rows=[], cols=_GET_COLS)
        repo = SystemRepository(pool)
        assert repo.get_current_mode() is None

    def test_returns_dict_with_latest_row_fields(self):
        pool, _ = _make_pool(
            rows=[("paper", _NOW, "env", None)],
            cols=_GET_COLS,
        )
        repo = SystemRepository(pool)
        assert repo.get_current_mode() == {
            "mode": "paper",
            "changed_at": _NOW,
            "source": "env",
            "actor": None,
        }


# ── insert_mode_change ────────────────────────────────────────────────────────

class TestInsertModeChange:

    def test_returns_inserted_row_dict(self):
        pool, _ = _make_pool(
            rows=[("real", _NOW, "api")],
            cols=_INSERT_COLS,
        )
        repo = SystemRepository(pool)
        result = repo.insert_mode_change(mode="real", source="api")
        assert result == {"mode": "real", "changed_at": _NOW, "source": "api"}

    def test_passes_all_params_to_execute(self):
        pool, cur = _make_pool(
            rows=[("real", _NOW, "api")],
            cols=_INSERT_COLS,
        )
        repo = SystemRepository(pool)
        repo.insert_mode_change(
            mode="real",
            source="api",
            confirmation_token="TOKEN-X",
            actor="juan",
            notes="manual flip",
        )
        params = cur.execute.call_args[0][1]
        assert params == ("real", "api", "TOKEN-X", "juan", "manual flip")

    def test_optional_fields_default_to_none(self):
        pool, cur = _make_pool(
            rows=[("paper", _NOW, "env")],
            cols=_INSERT_COLS,
        )
        repo = SystemRepository(pool)
        repo.insert_mode_change(mode="paper", source="env")
        params = cur.execute.call_args[0][1]
        assert params == ("paper", "env", None, None, None)

    def test_logs_info_with_mode_source_actor(self, caplog):
        pool, _ = _make_pool(
            rows=[("real", _NOW, "api")],
            cols=_INSERT_COLS,
        )
        repo = SystemRepository(pool)
        with caplog.at_level(logging.INFO):
            repo.insert_mode_change(mode="real", source="api", actor="juan")
        assert "mode_change_recorded" in caplog.text
        assert "mode=real" in caplog.text
        assert "source=api" in caplog.text
        assert "actor=juan" in caplog.text
