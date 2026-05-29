"""Tests for SchwabClient singleton DI lifespan (Sprint 14 f-r16-a + b).

Sprint 14 Bundle B1: F-r16 cross-cutting tech debt resolution (ADR-013 §9.3 #6
+ ADR-005 §9.3 #1 reaffirmed). 4 SchwabClient instances → 1 singleton via
app.state.schwab_client lifespan pattern.

Production refactor: S.14.f-r16-a (commit 0c8c59f).
Tests coverage: S.14.f-r16-b (this file).

Tests scope:
- TestBuildSchwabClient (7): _build_schwab_client helper lazy conditional
  + fail-fast contract D-ν + account_id strategy verify.
- TestHelperBackwardCompat (2): kwarg=None fallback preserves existing tests
  (10+ existing tests calling helpers SIN schwab_client kwarg unchanged).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from multi_agent.api.app import (
    _build_schwab_client,
    _build_snapshot_builder,
    _select_data_layer,
)
from multi_agent.config import Settings


def _make_settings(**overrides) -> Settings:
    """Build Settings with overrides, NO load .env file (mirror existing precedent)."""
    return Settings(_env_file=None, **overrides)


class TestBuildSchwabClient:
    """`_build_schwab_client` lazy conditional + fail-fast D-ν + account_id."""

    def test_returns_none_when_full_synthetic_mode(self):
        """Both flags False → None (NO eager GCP call)."""
        settings = _make_settings(
            USE_SCHWAB_DATA_LAYER=False,
            USE_LIVE_PORTFOLIO=False,
        )
        result = _build_schwab_client(settings)
        assert result is None

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_returns_client_when_schwab_data_layer_enabled(self, mock_from_gcp):
        """USE_SCHWAB_DATA_LAYER=True → SchwabClient instance (account_id=None)."""
        mock_client = MagicMock()
        mock_from_gcp.return_value = mock_client

        settings = _make_settings(
            USE_SCHWAB_DATA_LAYER=True,
            USE_LIVE_PORTFOLIO=False,
        )
        result = _build_schwab_client(settings)

        assert result is mock_client
        mock_from_gcp.assert_called_once_with(account_id=None)

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_returns_client_when_live_portfolio_enabled(self, mock_from_gcp):
        """USE_LIVE_PORTFOLIO=True + SCHWAB_ACCOUNT_ID set → SchwabClient con account_id."""
        mock_client = MagicMock()
        mock_from_gcp.return_value = mock_client

        settings = _make_settings(
            USE_SCHWAB_DATA_LAYER=False,
            USE_LIVE_PORTFOLIO=True,
            SCHWAB_ACCOUNT_ID="123456789",
        )
        result = _build_schwab_client(settings)

        assert result is mock_client
        mock_from_gcp.assert_called_once_with(account_id="123456789")

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_account_id_passed_when_live_portfolio(self, mock_from_gcp):
        """Verify from_gcp called con account_id kwarg explicit (F-r ant #5)."""
        mock_from_gcp.return_value = MagicMock()

        settings = _make_settings(
            USE_LIVE_PORTFOLIO=True,
            SCHWAB_ACCOUNT_ID="explicit_123",
        )
        _build_schwab_client(settings)

        mock_from_gcp.assert_called_once_with(account_id="explicit_123")

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_account_id_none_when_only_data_layer(self, mock_from_gcp):
        """USE_SCHWAB_DATA_LAYER=True, USE_LIVE_PORTFOLIO=False → account_id=None.

        Auto-discovery preserved for non-portfolio market data endpoints.
        """
        mock_from_gcp.return_value = MagicMock()

        settings = _make_settings(
            USE_SCHWAB_DATA_LAYER=True,
            USE_LIVE_PORTFOLIO=False,
        )
        _build_schwab_client(settings)

        mock_from_gcp.assert_called_once_with(account_id=None)

    def test_fail_fast_raises_when_live_portfolio_no_account_id(self):
        """Fail-fast contract D-ν preserved: USE_LIVE_PORTFOLIO=True + SCHWAB_ACCOUNT_ID="" → ValueError."""
        settings = _make_settings(
            USE_LIVE_PORTFOLIO=True,
            SCHWAB_ACCOUNT_ID="",
        )
        with pytest.raises(ValueError, match="SCHWAB_ACCOUNT_ID explicit"):
            _build_schwab_client(settings)

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_both_flags_enabled_account_id_explicit(self, mock_from_gcp):
        """USE_SCHWAB_DATA_LAYER=True + USE_LIVE_PORTFOLIO=True + account_id → singleton con account_id."""
        mock_from_gcp.return_value = MagicMock()

        settings = _make_settings(
            USE_SCHWAB_DATA_LAYER=True,
            USE_LIVE_PORTFOLIO=True,
            SCHWAB_ACCOUNT_ID="bundle_b1_account",
        )
        _build_schwab_client(settings)

        mock_from_gcp.assert_called_once_with(account_id="bundle_b1_account")


class TestHelperBackwardCompat:
    """`_select_data_layer` + `_build_snapshot_builder` kwarg=None fallback."""

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_select_data_layer_with_schwab_client_param_skips_internal_from_gcp(
        self, mock_from_gcp
    ):
        """Pass shared client kwarg → from_gcp NOT called (singleton path)."""
        shared_client = MagicMock()
        # Mock data_layer constructor (avoid SchwabDataLayer real instantiation)
        with patch("multi_agent.data_layer.SchwabDataLayer") as mock_data_layer_cls:
            mock_data_layer_cls.return_value = MagicMock()

            settings = _make_settings(USE_SCHWAB_DATA_LAYER=True)
            _select_data_layer(settings, schwab_client=shared_client)

            # SchwabDataLayer called con shared client (NOT internal from_gcp)
            mock_data_layer_cls.assert_called_once()
            args, kwargs = mock_data_layer_cls.call_args
            assert args[0] is shared_client  # positional first arg
            mock_from_gcp.assert_not_called()  # singleton path

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_build_snapshot_builder_with_schwab_client_param_skips_internal_from_gcp(
        self, mock_from_gcp
    ):
        """Pass shared client kwarg → from_gcp NOT called (singleton path)."""
        shared_client = MagicMock()
        pool_mock = MagicMock()
        # Mock LiveSnapshotBuilder constructor
        with patch("multi_agent.risk.portfolio_snapshot.LiveSnapshotBuilder") as mock_live_cls:
            mock_live_cls.return_value = MagicMock()

            settings = _make_settings(
                USE_LIVE_PORTFOLIO=True,
                SCHWAB_ACCOUNT_ID="test_123",
            )
            _build_snapshot_builder(settings, pool_mock, schwab_client=shared_client)

            # LiveSnapshotBuilder called con shared client (NOT internal from_gcp)
            mock_live_cls.assert_called_once_with(shared_client)
            mock_from_gcp.assert_not_called()  # singleton path
