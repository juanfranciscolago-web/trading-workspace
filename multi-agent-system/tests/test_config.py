"""Tests for multi_agent.config Settings (Sprint 11 atlas-d additions).

Covers ADR-013 D9-1 (SCHWAB_ACCOUNT_ID) + D10 (USE_LIVE_PORTFOLIO).
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from multi_agent.config import Settings


# Minimum env vars required to construct Settings (pydantic-settings validators).
_BASE_ENV = {
    "DATABASE_URL": "postgresql://trader:trader@localhost:5432/trading",
    "REDIS_URL": "redis://localhost:6379/0",
    "ANTHROPIC_API_KEY": "sk-test",
}


class TestSettingsPhase11AtlasD:
    """Settings field defaults + env override (ADR-013 D9-1 + D10)."""

    def test_use_live_portfolio_default_false(self):
        """USE_LIVE_PORTFOLIO defaults False (synthetic SnapshotBuilder)."""
        with patch.dict(os.environ, _BASE_ENV, clear=True):
            settings = Settings()
            assert settings.USE_LIVE_PORTFOLIO is False

    def test_schwab_account_id_default_empty(self):
        """SCHWAB_ACCOUNT_ID defaults empty string (auto-discovery)."""
        with patch.dict(os.environ, _BASE_ENV, clear=True):
            settings = Settings()
            assert settings.SCHWAB_ACCOUNT_ID == ""

    def test_use_live_portfolio_environment_override(self):
        """USE_LIVE_PORTFOLIO can be set via env var."""
        env = {**_BASE_ENV, "USE_LIVE_PORTFOLIO": "true"}
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()
            assert settings.USE_LIVE_PORTFOLIO is True
