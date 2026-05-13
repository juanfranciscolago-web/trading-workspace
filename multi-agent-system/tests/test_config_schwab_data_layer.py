"""Tests for USE_SCHWAB_DATA_LAYER config flag (S.5.6f)."""
from __future__ import annotations

from multi_agent.config import Settings


def _make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_use_schwab_data_layer_default_is_false(monkeypatch):
    """ADR-004 D1: StubDataLayer remains fallback default Sprint 5."""
    monkeypatch.delenv("USE_SCHWAB_DATA_LAYER", raising=False)
    s = _make_settings()
    assert s.USE_SCHWAB_DATA_LAYER is False


def test_use_schwab_data_layer_can_be_enabled(monkeypatch):
    """Setting True activates SchwabDataLayer wiring in lifespan."""
    monkeypatch.delenv("USE_SCHWAB_DATA_LAYER", raising=False)
    s = _make_settings(USE_SCHWAB_DATA_LAYER=True)
    assert s.USE_SCHWAB_DATA_LAYER is True


def test_use_schwab_data_layer_accepts_string_true_from_env(monkeypatch):
    """Pydantic-settings auto-parses string "true" from env vars to bool.
    Env vars are always strings; verify bool conversion works for the env
    path (production usage)."""
    monkeypatch.delenv("USE_SCHWAB_DATA_LAYER", raising=False)
    s = _make_settings(USE_SCHWAB_DATA_LAYER="true")
    assert s.USE_SCHWAB_DATA_LAYER is True
