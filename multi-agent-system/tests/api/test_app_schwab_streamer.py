"""Tests for SchwabStreamer singleton lifespan DI (Sprint 15 ws-a + ADR-010 Phase 1).

Sprint 15 Bundle C3: ADR-010 Schwab WebSocket Port Phase 1 (connection + auth + LOGIN).
Production: S.15.ws-a (this sub-block).

Tests scope (Phase 1 mock-based per ADR-010 D8):
- TestBuildSchwabStreamer (3): lazy conditional + USE_SCHWAB_WEBSOCKET flag + schwab_client None.
- TestSchwabStreamerInit (2): ctor stores client + initial state.
- TestSchwabStreamerConnectMock (2): connect() mock + LOGIN verify + LOGIN failure raises.

Integration tests deferred Phase 2 (per ADR-010 D8).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_agent.api.app import _build_schwab_streamer
from multi_agent.config import Settings
from shared_core.brokers.schwab_streamer import SchwabStreamer


def _make_settings(**overrides) -> Settings:
    """Build Settings with overrides, NO load .env (mirror existing precedent)."""
    return Settings(_env_file=None, **overrides)


class TestBuildSchwabStreamer:
    """`_build_schwab_streamer` lazy conditional + USE_SCHWAB_WEBSOCKET flag."""

    def test_returns_none_when_websocket_flag_false(self):
        """USE_SCHWAB_WEBSOCKET=False → None."""
        settings = _make_settings(USE_SCHWAB_WEBSOCKET=False)
        result = _build_schwab_streamer(settings, schwab_client=MagicMock())
        assert result is None

    def test_returns_none_when_schwab_client_none(self):
        """USE_SCHWAB_WEBSOCKET=True + schwab_client=None → None (cannot auth)."""
        settings = _make_settings(USE_SCHWAB_WEBSOCKET=True)
        result = _build_schwab_streamer(settings, schwab_client=None)
        assert result is None

    def test_returns_streamer_when_both_viable(self):
        """USE_SCHWAB_WEBSOCKET=True + schwab_client → SchwabStreamer instance."""
        settings = _make_settings(USE_SCHWAB_WEBSOCKET=True)
        mock_client = MagicMock()
        result = _build_schwab_streamer(settings, schwab_client=mock_client)
        assert isinstance(result, SchwabStreamer)
        assert result._client is mock_client


class TestSchwabStreamerInit:
    """SchwabStreamer ctor + initial state."""

    def test_ctor_stores_schwab_client(self):
        """SchwabStreamer ctor stores schwab_client reference."""
        mock_client = MagicMock()
        streamer = SchwabStreamer(schwab_client=mock_client)
        assert streamer._client is mock_client

    def test_ctor_initial_state(self):
        """SchwabStreamer ctor initial state: not connected, no ws, no streamer_info."""
        mock_client = MagicMock()
        streamer = SchwabStreamer(schwab_client=mock_client)
        assert streamer._ws is None
        assert streamer._streamer_info is None
        assert streamer._connected is False
        assert streamer.is_connected is False


class TestSchwabStreamerConnectMock:
    """SchwabStreamer connect() mock httpx + websockets."""

    @pytest.mark.asyncio
    async def test_connect_fetches_user_preferences_via_get_trader_v1(self):
        """connect() calls GET /trader/v1/userPreference (D-γ-17 amendment verify)."""
        mock_client = MagicMock()
        mock_client.credentials.access_token = "test_token"
        mock_client._ensure_authenticated = MagicMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "streamerInfo": [{
                "streamerSocketUrl": "wss://streamer-api.schwab.com/ws",
                "schwabClientCustomerId": "test_customer",
                "schwabClientCorrelId": "test_correl",
                "schwabClientChannel": "test_channel",
                "schwabClientFunctionId": "test_function",
            }]
        }

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"response":[{"content":{"code":0}}]}')

        with patch("shared_core.brokers.schwab_streamer.httpx.get", return_value=mock_response) as mock_http_get, \
             patch("shared_core.brokers.schwab_streamer.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):

            streamer = SchwabStreamer(schwab_client=mock_client)
            await streamer.connect()

            # Verify GET /trader/v1/userPreference URL (D-γ-17 amendment)
            mock_http_get.assert_called_once()
            call_args = mock_http_get.call_args
            url = call_args[0][0]
            assert "/trader/v1/userPreference" in url

            # Verify connected
            assert streamer._connected is True

    @pytest.mark.asyncio
    async def test_connect_raises_on_login_failure(self):
        """connect() raises ConnectionError if LOGIN response code != 0."""
        mock_client = MagicMock()
        mock_client.credentials.access_token = "test_token"
        mock_client._ensure_authenticated = MagicMock()

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "streamerInfo": [{
                "streamerSocketUrl": "wss://streamer-api.schwab.com/ws",
                "schwabClientCustomerId": "test_customer",
                "schwabClientCorrelId": "test_correl",
                "schwabClientChannel": "test_channel",
                "schwabClientFunctionId": "test_function",
            }]
        }

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"response":[{"content":{"code":3,"msg":"auth failed"}}]}')

        with patch("shared_core.brokers.schwab_streamer.httpx.get", return_value=mock_response), \
             patch("shared_core.brokers.schwab_streamer.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):

            streamer = SchwabStreamer(schwab_client=mock_client)
            with pytest.raises(ConnectionError, match="LOGIN failed"):
                await streamer.connect()
