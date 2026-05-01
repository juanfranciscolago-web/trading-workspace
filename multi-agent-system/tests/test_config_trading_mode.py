from __future__ import annotations

import pytest
from pydantic import ValidationError

from multi_agent.config import (
    REAL_MODE_HUMAN_MESSAGE,
    REAL_MODE_TOKEN,
    Settings,
    TradingMode,
)


def _make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_default_is_paper(monkeypatch):
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("TRADING_MODE_CONFIRM", raising=False)
    s = _make_settings()
    assert s.TRADING_MODE == TradingMode.PAPER


def test_paper_mode_works_without_confirm():
    s = _make_settings(TRADING_MODE="paper")
    assert s.TRADING_MODE == TradingMode.PAPER


def test_real_mode_with_correct_confirm():
    s = _make_settings(TRADING_MODE="real", TRADING_MODE_CONFIRM=REAL_MODE_TOKEN)
    assert s.TRADING_MODE == TradingMode.REAL


def test_real_mode_without_confirm_fails():
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(TRADING_MODE="real")
    msg = str(exc_info.value)
    assert REAL_MODE_HUMAN_MESSAGE in msg
    assert "TRADING_MODE_CONFIRM" in msg


def test_real_mode_with_wrong_confirm_fails():
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(TRADING_MODE="real", TRADING_MODE_CONFIRM="wrong_token")
    msg = str(exc_info.value)
    assert REAL_MODE_HUMAN_MESSAGE in msg
    assert "TRADING_MODE_CONFIRM" in msg


def test_real_mode_with_whitespace_in_confirm_fails():
    with pytest.raises(ValidationError) as exc_info:
        _make_settings(TRADING_MODE="real", TRADING_MODE_CONFIRM=f" {REAL_MODE_TOKEN}")
    msg = str(exc_info.value)
    assert REAL_MODE_HUMAN_MESSAGE in msg
    assert "TRADING_MODE_CONFIRM" in msg

    with pytest.raises(ValidationError) as exc_info:
        _make_settings(TRADING_MODE="real", TRADING_MODE_CONFIRM=f"{REAL_MODE_TOKEN} ")
    msg = str(exc_info.value)
    assert REAL_MODE_HUMAN_MESSAGE in msg
    assert "TRADING_MODE_CONFIRM" in msg
