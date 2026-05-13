"""
Schwab API client — unified wrapper for both Eolo and the multi-agent system.

This is the SINGLE point of contact with Schwab. Both systems import from here
to avoid duplicating authentication, rate limiting, and error handling.

Usage:
    from shared_core.brokers import SchwabClient

    client = SchwabClient.from_env()  # Loads credentials from env vars
    quote = client.get_quote("MSFT")
    chain = client.get_options_chain("MSFT", expiration="2026-06-19")
"""

from __future__ import annotations

import base64
import logging
import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

import httpx

from ..auth.gcp import (
    retrieve_firestore_value,
    retrieve_google_secret_dict,
    store_firestore_value,
)

logger = logging.getLogger(__name__)


class SchwabAuthError(RuntimeError):
    """Raised when Schwab OAuth refresh fails non-recoverably."""


@dataclass
class SchwabCredentials:
    """Credentials for Schwab API authentication."""
    api_key: str
    api_secret: str
    refresh_token: Optional[str] = None
    access_token: Optional[str] = None
    token_expires_at: Optional[float] = None  # Unix timestamp


class RateLimiter:
    """Simple token bucket rate limiter for Schwab API."""

    def __init__(self, max_calls_per_second: int = 5):
        self.max_calls = max_calls_per_second
        self.call_times: list[float] = []

    def wait_if_needed(self) -> None:
        """Block until we're under the rate limit."""
        now = time.time()
        # Drop calls older than 1 second
        self.call_times = [t for t in self.call_times if now - t < 1.0]

        if len(self.call_times) >= self.max_calls:
            # Sleep until oldest call falls outside the window
            sleep_time = 1.0 - (now - self.call_times[0]) + 0.01
            if sleep_time > 0:
                time.sleep(sleep_time)
                # Refresh after sleep
                now = time.time()
                self.call_times = [t for t in self.call_times if now - t < 1.0]

        self.call_times.append(now)


class SchwabClient:
    """
    Unified Schwab API client.

    NOTE: This is a skeleton. Actual HTTP integration with Schwab requires:
        - OAuth flow setup (one-time, see Schwab developer docs)
        - HTTP client (httpx or requests)
        - Token refresh logic

    The structure here is what both Eolo and multi-agent should consume.
    Implementation details (HTTP calls) are marked as TODO and should be
    filled in by porting from Eolo's existing implementation.
    """

    BASE_URL = "https://api.schwabapi.com"

    # GCP locations (mirrors Eolo's pattern: init_auth.py + main.py).
    GCP_PROJECT_ID = "eolo-schwab-agent"
    APP_KEY_SECRET_ID = "cs-app-key"
    TOKEN_COLLECTION = "schwab-tokens"
    TOKEN_DOCUMENT = "schwab-tokens-auth"
    OAUTH_TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
    DEFAULT_TOKEN_TTL_SECONDS = 1800  # Schwab default ~30min if expires_in missing

    def __init__(
        self,
        credentials: SchwabCredentials,
        paper_trading: bool = True,
        rate_limit_per_second: int = 5,
    ):
        self.credentials = credentials
        self.paper_trading = paper_trading
        self.rate_limiter = RateLimiter(rate_limit_per_second)
        self._http_client = None  # Initialize lazily
        # Per-instance lock prevents two threads from racing on refresh; the
        # second POST would invalidate the first's tokens (Schwab rotates).
        self._refresh_lock = threading.Lock()

        if paper_trading:
            logger.info("SchwabClient initialized in PAPER trading mode")
        else:
            logger.warning("SchwabClient initialized in LIVE trading mode")

    @classmethod
    def from_env(cls, paper_trading: bool = True) -> SchwabClient:
        """Initialize from environment variables."""
        creds = SchwabCredentials(
            api_key=os.environ["SCHWAB_API_KEY"],
            api_secret=os.environ["SCHWAB_API_SECRET"],
            refresh_token=os.environ.get("SCHWAB_REFRESH_TOKEN"),
        )
        return cls(credentials=creds, paper_trading=paper_trading)

    # -------------------------------------------------------------------------
    # Authentication
    # -------------------------------------------------------------------------

    def _ensure_authenticated(self) -> None:
        """Refresh access token if expired."""
        if self.credentials.access_token is None:
            self._refresh_access_token()
            return

        if self.credentials.token_expires_at is None:
            return

        # Refresh if expires in less than 60 seconds
        if time.time() > self.credentials.token_expires_at - 60:
            self._refresh_access_token()

    def _refresh_access_token(self) -> None:
        """Refresh the OAuth access token using the refresh token in Firestore.

        Pattern ported from Eolo's main.py (refresh_tokens Cloud Function).
        Schwab rotates BOTH access_token AND refresh_token on each call —
        the full response dict replaces the Firestore document atomically.

        Thread-safe: a per-instance lock serializes concurrent refresh
        attempts (two POSTs would race and invalidate each other).

        Raises:
            SchwabAuthError: If Firestore lacks a refresh_token (operator
                must run safe_init_auth_v2.py once to bootstrap), if Schwab
                returns non-200, or if the response is missing required
                fields.
        """
        with self._refresh_lock:
            start = time.time()
            logger.info("Refreshing Schwab access token")

            # 1. App credentials from Secret Manager.
            app_creds = retrieve_google_secret_dict(
                gcp_id=self.GCP_PROJECT_ID,
                secret_id=self.APP_KEY_SECRET_ID,
            )
            app_key = app_creds["app-key"]
            app_secret = app_creds["app-secret"]

            # 2. Current refresh_token from Firestore.
            refresh_token = retrieve_firestore_value(
                collection_id=self.TOKEN_COLLECTION,
                document_id=self.TOKEN_DOCUMENT,
                key="refresh_token",
                project_id=self.GCP_PROJECT_ID,
            )
            if refresh_token is None:
                raise SchwabAuthError(
                    f"No refresh_token in Firestore "
                    f"{self.TOKEN_COLLECTION}/{self.TOKEN_DOCUMENT}. "
                    f"Run safe_init_auth_v2.py to bootstrap."
                )

            # 3. POST to Schwab /oauth/token with refresh_token grant.
            basic = base64.b64encode(f"{app_key}:{app_secret}".encode()).decode()
            headers = {
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
            response = httpx.post(
                self.OAUTH_TOKEN_URL,
                headers=headers,
                data=payload,
                timeout=10,
            )
            if response.status_code != 200:
                raise SchwabAuthError(
                    f"Schwab /oauth/token returned {response.status_code}: "
                    f"{response.text[:200]}"
                )

            new_tokens = response.json()
            missing = [
                f for f in ("access_token", "refresh_token", "expires_in")
                if f not in new_tokens
            ]
            if missing:
                raise SchwabAuthError(
                    f"Schwab response missing required fields: {missing}. "
                    f"Got keys: {list(new_tokens.keys())}"
                )

            # 4. Persist full dict to Firestore (Schwab rotated BOTH tokens).
            store_firestore_value(
                project_id=self.GCP_PROJECT_ID,
                collection_id=self.TOKEN_COLLECTION,
                document_id=self.TOKEN_DOCUMENT,
                value=new_tokens,
            )

            # 5. Update in-memory credentials.
            self.credentials.access_token = new_tokens["access_token"]
            self.credentials.refresh_token = new_tokens["refresh_token"]
            expires_in = new_tokens.get("expires_in", self.DEFAULT_TOKEN_TTL_SECONDS)
            self.credentials.token_expires_at = time.time() + expires_in

            duration_ms = (time.time() - start) * 1000
            logger.info(
                "Schwab access token refreshed (expires_in=%ds, duration=%.0fms)",
                expires_in, duration_ms,
            )

    # -------------------------------------------------------------------------
    # Market data
    # -------------------------------------------------------------------------

    def get_quote(self, symbol: str) -> dict:
        """
        Get current quote for a symbol.

        Returns:
            dict with keys: bid, ask, last, volume, timestamp
        """
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        # TODO: Port from Eolo. Should call:
        # GET /marketdata/v1/{symbol}/quotes
        raise NotImplementedError("Port from Eolo: get_quote")

    def get_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Batch quote retrieval. More efficient than get_quote in a loop."""
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        # TODO: Port from Eolo
        raise NotImplementedError("Port from Eolo: get_quotes batch")

    def get_options_chain(
        self,
        underlying: str,
        expiration: Optional[str] = None,
        strike_count: int = 20,
    ) -> dict:
        """
        Get options chain for an underlying.

        Args:
            underlying: Stock ticker
            expiration: Specific expiration date (YYYY-MM-DD), or None for all
            strike_count: Number of strikes around ATM

        Returns:
            dict with calls and puts arrays, each containing strike, bid, ask,
            last, volume, OI, IV, Greeks
        """
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        # TODO: Port from Eolo
        raise NotImplementedError("Port from Eolo: get_options_chain")

    def get_price_history(
        self,
        symbol: str,
        period_type: str = "day",
        period: int = 30,
        frequency_type: str = "minute",
        frequency: int = 1,
    ) -> list[dict]:
        """Get OHLCV history."""
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        # TODO: Port from Eolo
        raise NotImplementedError("Port from Eolo: get_price_history")

    # -------------------------------------------------------------------------
    # Account state
    # -------------------------------------------------------------------------

    def get_positions(self) -> list[dict]:
        """Get all open positions in the account."""
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        # TODO: Port from Eolo
        raise NotImplementedError("Port from Eolo: get_positions")

    def get_balances(self) -> dict:
        """
        Get account balances.

        Returns:
            dict with: cash, buying_power, margin_used, total_value, etc.
        """
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        # TODO: Port from Eolo
        raise NotImplementedError("Port from Eolo: get_balances")

    # -------------------------------------------------------------------------
    # Order management
    # -------------------------------------------------------------------------

    def place_order(self, order: dict) -> dict:
        """
        Place an order.

        Args:
            order: Schwab order dict (see Schwab API docs)

        Returns:
            dict with: order_id, status, fills

        IMPORTANT: This method should NEVER be called directly.
        ALL trades must go through the risk validator (atlas_client) first.
        """
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        if not self.paper_trading:
            logger.warning(
                f"LIVE TRADE about to be placed: {order}. "
                f"Verify atlas validation occurred upstream."
            )

        # TODO: Port from Eolo
        raise NotImplementedError("Port from Eolo: place_order")

    def cancel_order(self, order_id: str) -> dict:
        """Cancel a pending order."""
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        # TODO: Port from Eolo
        raise NotImplementedError("Port from Eolo: cancel_order")

    def get_order_status(self, order_id: str) -> dict:
        """Check status of a specific order."""
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        # TODO: Port from Eolo
        raise NotImplementedError("Port from Eolo: get_order_status")
