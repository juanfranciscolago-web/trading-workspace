"""Schwab WebSocket Streamer — Phase 1 (ADR-010).

Port from Eolo eolo-options/stream/options_stream.py + Bot-v1.2/stream.py
(mirror Sprint 11 atlas-b/c port pattern).

Phase 1 scope (per ADR-010 D1):
- Connection establishment (handshake + LOGIN).
- Heartbeat keepalive (websockets ping_interval).
- Disconnect cleanup.

Phase 2 scope (Sprint 16+, deferred per ADR-010 D5/D6/D7):
- Subscription protocol (SUBS/ADD/UNSUBS commands).
- Message handlers per service (LEVELONE_EQUITIES + CHART_EQUITY).
- Full reconnection logic (exponential backoff).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

import httpx
import websockets

from shared_core.brokers.schwab_client import SchwabClient

logger = logging.getLogger(__name__)


class SchwabStreamer:
    """Schwab Streaming API WebSocket client (ADR-010 Phase 1).

    Mirrors Eolo precedent eolo-options/stream/options_stream.py +
    Bot-v1.2/stream.py adapted for multi-agent shared_core context.

    Auth via SchwabClient REST OAuth access_token reuse (D-δ-16 + D-γ-17
    ADR-010 D3 amendment Sprint 15 ws-a: GET /trader/v1/userPreference per
    Eolo precedent).
    """

    USER_PREFERENCE_PATH = "/userPreference"  # appended to TRADER_BASE_URL (D-γ-17)
    PING_INTERVAL = 20  # seconds (per Eolo precedent)
    PING_TIMEOUT = 10   # seconds (per Eolo precedent)

    def __init__(self, schwab_client: SchwabClient):
        """Initialize SchwabStreamer with shared SchwabClient (F-r16 singleton).

        Args:
            schwab_client: shared SchwabClient instance (provides
                credentials.access_token + TRADER_BASE_URL class constant).
        """
        self._client = schwab_client
        self._ws: Optional[Any] = None  # websockets.ClientConnection (16.0 API)
        self._streamer_info: Optional[dict[str, Any]] = None
        self._request_id = 0
        self._connected = False

    async def connect(self) -> None:
        """Connect to Schwab Streaming API + authenticate.

        Steps (per Eolo precedent):
        1. GET /trader/v1/userPreference → fetch streamer info (URL + customer ID).
        2. websockets.connect(streamer_url, ping_interval=20, ping_timeout=10).
        3. LOGIN command via streamer protocol.
        4. Verify response code == 0.

        Raises:
            ConnectionError: if LOGIN response code != 0 or connection fails.
        """
        # Step 1: Fetch streamer info via REST GET (D-γ-17 amendment)
        self._streamer_info = await self._fetch_user_preferences()

        # Step 2: WebSocket connect with auto-heartbeat
        streamer_info_first = self._streamer_info.get("streamerInfo", [{}])[0]
        streamer_url = streamer_info_first.get("streamerSocketUrl")
        if not streamer_url:
            raise ConnectionError(
                "Schwab streamerSocketUrl missing from userPreference response"
            )

        self._ws = await websockets.connect(
            streamer_url,
            ping_interval=self.PING_INTERVAL,
            ping_timeout=self.PING_TIMEOUT,
        )
        logger.info("✓ SchwabStreamer WebSocket connected (url=%s)", streamer_url)

        # Step 3-4: LOGIN + verify response code 0
        await self._login()
        self._connected = True
        logger.info("✓ SchwabStreamer authenticated (LOGIN code=0)")

    async def _fetch_user_preferences(self) -> dict[str, Any]:
        """GET /trader/v1/userPreference via httpx sync wrapped (D-γ-17 amendment).

        Returns response JSON dict with streamerInfo[0] structure:
        - streamerSocketUrl: wss URL.
        - schwabClientCustomerId: customer ID for LOGIN.
        - schwabClientCorrelId: correlation ID.
        - schwabClientChannel: channel.
        - schwabClientFunctionId: function ID.

        Uses SchwabClient.TRADER_BASE_URL class constant + asyncio.to_thread
        for sync httpx call in async context (mirror SchwabClient REST pattern).
        """
        # Ensure token fresh (sync method in SchwabClient)
        await asyncio.to_thread(self._client._ensure_authenticated)

        url = f"{SchwabClient.TRADER_BASE_URL}{self.USER_PREFERENCE_PATH}"
        headers = {
            "Authorization": f"Bearer {self._client.credentials.access_token}",
            "Accept": "application/json",
        }

        response = await asyncio.to_thread(
            httpx.get, url, headers=headers, timeout=10
        )
        response.raise_for_status()
        return response.json()

    async def _login(self) -> None:
        """Send LOGIN command via WebSocket (Eolo precedent payload format).

        Raises:
            ConnectionError: if response code != 0.
        """
        streamer_info_first = self._streamer_info["streamerInfo"][0]
        self._request_id += 1

        login_payload = {
            "requests": [{
                "service": "ADMIN",
                "command": "LOGIN",
                "requestid": str(self._request_id),
                "SchwabClientCustomerId": streamer_info_first["schwabClientCustomerId"],
                "SchwabClientCorrelId": streamer_info_first["schwabClientCorrelId"],
                "parameters": {
                    "Authorization": self._client.credentials.access_token,
                    "SchwabClientChannel": streamer_info_first["schwabClientChannel"],
                    "SchwabClientFunctionId": streamer_info_first["schwabClientFunctionId"],
                },
            }]
        }

        await self._ws.send(json.dumps(login_payload))

        # Verify response code == 0
        response_raw = await self._ws.recv()
        response = json.loads(response_raw)

        login_response = response.get("response", [{}])[0]
        content = login_response.get("content", {})
        code = content.get("code", -1)

        if code != 0:
            raise ConnectionError(
                f"Schwab Streamer LOGIN failed: code={code} "
                f"msg={content.get('msg', 'unknown')}"
            )

    async def disconnect(self) -> None:
        """Cleanup WebSocket connection (Phase 1 minimal)."""
        if self._ws is not None:
            try:
                await self._ws.close()
                logger.info("✓ SchwabStreamer disconnected")
            except Exception as e:
                logger.warning("SchwabStreamer disconnect non-fatal error: %s", e)
        self._ws = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Connection status (Phase 1 introspection)."""
        return self._connected and self._ws is not None
