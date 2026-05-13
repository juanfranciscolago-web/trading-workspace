"""Tests for _select_data_layer (S.5.6f).

Verifies the lifespan branch behavior: which DataLayer is constructed
based on USE_SCHWAB_DATA_LAYER, and the fail-fast contract when GCP
construction fails.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from multi_agent.api.app import _select_data_layer
from multi_agent.config import Settings
from multi_agent.data_layer import SchwabDataLayer, StubDataLayer
from shared_core.brokers.schwab_client import SchwabAuthError


def _make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


class TestSelectDataLayer:

    def test_default_uses_stub_data_layer(self):
        """USE_SCHWAB_DATA_LAYER=False (default) → StubDataLayer."""
        settings = _make_settings(USE_SCHWAB_DATA_LAYER=False)
        result = _select_data_layer(settings)
        assert isinstance(result, StubDataLayer)

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_flag_enabled_uses_schwab_data_layer(self, mock_from_gcp):
        """USE_SCHWAB_DATA_LAYER=True with mocked GCP → SchwabDataLayer."""
        mock_client = MagicMock()
        mock_from_gcp.return_value = mock_client
        settings = _make_settings(USE_SCHWAB_DATA_LAYER=True)

        result = _select_data_layer(settings)

        assert isinstance(result, SchwabDataLayer)
        mock_from_gcp.assert_called_once()

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_flag_enabled_but_gcp_fails_raises(self, mock_from_gcp):
        """USE_SCHWAB_DATA_LAYER=True but from_gcp raises → propagates."""
        mock_from_gcp.side_effect = SchwabAuthError("No tokens in Firestore")
        settings = _make_settings(USE_SCHWAB_DATA_LAYER=True)

        with pytest.raises(SchwabAuthError, match="No tokens in Firestore"):
            _select_data_layer(settings)

    @patch("shared_core.brokers.schwab_client.SchwabClient.from_gcp")
    def test_flag_enabled_but_unexpected_error_also_raises(self, mock_from_gcp):
        """Any exception during from_gcp propagates (not just SchwabAuthError)."""
        mock_from_gcp.side_effect = RuntimeError("network down")
        settings = _make_settings(USE_SCHWAB_DATA_LAYER=True)

        with pytest.raises(RuntimeError, match="network down"):
            _select_data_layer(settings)
