"""Tests for _build_snapshot_builder() helper (S.11.atlas-e).

Covers ADR-013 D6 (LiveSnapshotBuilder selector) + D7 (TTL 30s live) +
D-μ (account_id passing) + D-ν STRENGTHENED + D-ο (fail-fast empty account_id).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from multi_agent.api.app import _build_snapshot_builder
from multi_agent.config import Settings
from multi_agent.risk.portfolio_snapshot import (
    CachedSnapshotBuilder,
    LiveSnapshotBuilder,
    SnapshotBuilder,
)


def _make_settings(**overrides) -> Settings:
    """Helper: construct Settings disabling .env file + override fields directly."""
    return Settings(_env_file=None, **overrides)


class TestBuildSnapshotBuilder:
    """_build_snapshot_builder() selector logic per USE_LIVE_PORTFOLIO flag."""

    def test_default_uses_db_snapshot_builder(self):
        """USE_LIVE_PORTFOLIO=False (default) → SnapshotBuilder + TTL 5s."""
        settings = _make_settings(USE_LIVE_PORTFOLIO=False)
        pool_mock = MagicMock()

        result = _build_snapshot_builder(settings, pool_mock)

        assert isinstance(result, CachedSnapshotBuilder)
        assert result._ttl == 5.0  # F-r17: attribute is _ttl (not _ttl_seconds)
        assert isinstance(result._builder, SnapshotBuilder)

    def test_flag_enabled_uses_live_snapshot_builder(self):
        """USE_LIVE_PORTFOLIO=True + account_id set → LiveSnapshotBuilder + TTL 30s."""
        settings = _make_settings(
            USE_LIVE_PORTFOLIO=True,
            SCHWAB_ACCOUNT_ID="123456789",
        )
        pool_mock = MagicMock()

        with patch(
            "shared_core.brokers.schwab_client.SchwabClient.from_gcp"
        ) as mock_from_gcp:
            mock_from_gcp.return_value = MagicMock()
            result = _build_snapshot_builder(settings, pool_mock)

        assert isinstance(result, CachedSnapshotBuilder)
        assert result._ttl == 30.0
        assert isinstance(result._builder, LiveSnapshotBuilder)

    def test_flag_enabled_passes_account_id_to_schwab_client(self):
        """D-μ + D9-1: account_id forwarded to SchwabClient.from_gcp()."""
        settings = _make_settings(
            USE_LIVE_PORTFOLIO=True,
            SCHWAB_ACCOUNT_ID="explicit_subaccount_999",
        )
        pool_mock = MagicMock()

        with patch(
            "shared_core.brokers.schwab_client.SchwabClient.from_gcp"
        ) as mock_from_gcp:
            mock_from_gcp.return_value = MagicMock()
            _build_snapshot_builder(settings, pool_mock)

        mock_from_gcp.assert_called_once_with(
            account_id="explicit_subaccount_999",
        )

    def test_flag_enabled_empty_account_id_raises_value_error(self):
        """D-ο fail-fast: USE_LIVE_PORTFOLIO=True + empty SCHWAB_ACCOUNT_ID → ValueError."""
        settings = _make_settings(
            USE_LIVE_PORTFOLIO=True,
            SCHWAB_ACCOUNT_ID="",
        )
        pool_mock = MagicMock()

        with pytest.raises(ValueError, match="SCHWAB_ACCOUNT_ID explicit"):
            _build_snapshot_builder(settings, pool_mock)

    def test_flag_enabled_uses_30s_ttl(self):
        """D7: TTL 30s applied live mode (vs 5s synthetic default)."""
        settings = _make_settings(
            USE_LIVE_PORTFOLIO=True,
            SCHWAB_ACCOUNT_ID="acct_123",
        )
        pool_mock = MagicMock()

        with patch(
            "shared_core.brokers.schwab_client.SchwabClient.from_gcp"
        ) as mock_from_gcp:
            mock_from_gcp.return_value = MagicMock()
            result = _build_snapshot_builder(settings, pool_mock)

        assert result._ttl == 30.0  # F-r17 _ttl attribute

    def test_flag_enabled_but_gcp_fails_raises(self):
        """If SchwabClient.from_gcp() fails, propagate (no silent fallback to DB)."""
        settings = _make_settings(
            USE_LIVE_PORTFOLIO=True,
            SCHWAB_ACCOUNT_ID="acct_123",
        )
        pool_mock = MagicMock()

        with patch(
            "shared_core.brokers.schwab_client.SchwabClient.from_gcp"
        ) as mock_from_gcp:
            mock_from_gcp.side_effect = RuntimeError("GCP secret access failed")
            with pytest.raises(RuntimeError, match="GCP secret access failed"):
                _build_snapshot_builder(settings, pool_mock)
