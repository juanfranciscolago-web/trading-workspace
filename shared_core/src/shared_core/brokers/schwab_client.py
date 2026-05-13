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


class SchwabAPIError(RuntimeError):
    """Raised when Schwab Market Data API returns a non-recoverable error."""


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
    PRICE_HISTORY_URL = "https://api.schwabapi.com/marketdata/v1/pricehistory"
    CHAINS_URL = "https://api.schwabapi.com/marketdata/v1/chains"
    DEFAULT_STRIKE_COUNT = 20
    DEFAULT_OPTIONS_CONTRACT_TYPE = "ALL"
    DEFAULT_OPTIONS_STRATEGY = "SINGLE"
    DEFAULT_OPTIONS_RANGE = "ALL"
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
        strike_count: int = DEFAULT_STRIKE_COUNT,
    ) -> dict:
        """Fetch options chain for an underlying via Schwab Market Data API.

        Pattern ported from Eolo's eolo-options/stream/options_chain.py
        (_fetch_chain + _normalize + _parse_option_map). Returns a normalized
        chain dict — Schwab's raw response uses an awkward nested map keyed
        by "YYYY-MM-DD:DTE" with single-element contract lists, which we
        unwrap so consumers (SchwabDataLayer S.5.6e onwards) work with a
        clean structure.

        Args:
            underlying: Stock ticker (e.g. "SPY", "QQQ").
            expiration: Single date YYYY-MM-DD to filter to (sets Schwab
                fromDate=toDate=expiration). None → all expirations.
            strike_count: Strikes ABOVE and BELOW ATM (so 2*N total).
                Default 20 → ~40 strikes returned.

        Returns:
            Normalized chain dict with this shape (all numerics float or
            int; absent Schwab fields default to 0.0 / 0):

                {
                    "underlying": "SPY",
                    "ts":         <unix_float>,
                    "spot": {
                        "last":       float,
                        "bid":        float,
                        "ask":        float,
                        "mark":       float,
                        "volatility": float,  # HV from Schwab
                    },
                    "calls": {
                        "2026-06-19": {           # exp_date str
                            "450.0": {            # strike str (Schwab format)
                                "bid":   float,
                                "ask":   float,
                                "mark":  float,
                                "last":  float,
                                "iv":    float,   # Schwab "volatility"
                                "delta": float,
                                "gamma": float,
                                "theta": float,
                                "vega":  float,
                                "volume": int,    # Schwab "totalVolume"
                                "oi":     int,    # Schwab "openInterest"
                                "dte":    int,    # computed from exp_key
                            },
                            ...
                        },
                        ...
                    },
                    "puts":  { ...same shape as calls... },
                    "expirations": ["2026-06-19", ...],  # sorted ascending
                }

        Raises:
            SchwabAPIError: If Schwab returns non-200 (after one 401 retry).
                Network errors propagate natively (httpx.RequestError).
            SchwabAuthError: If the 401 retry's _refresh_access_token fails.

        Notes:
            - Strike dict keys are strings (Schwab native format). Convert at
              iteration time: `float(strike_str)`. Strike is NOT included as
              a field inside the contract — the outer dict key is the source
              of truth.
            - Defensive defaults: missing numeric fields → 0.0 (or 0 for
              int counts). Schwab occasionally returns explicit None for
              greeks on deep OTM/ITM strikes; the `or 0.0` idiom catches
              both missing-key and None-value cases.
            - 401 retry pattern is consistent with get_price_history
              (max 1 retry with explicit _refresh_access_token in between).
        """
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        params = {
            "symbol":                 underlying,
            "contractType":           self.DEFAULT_OPTIONS_CONTRACT_TYPE,
            "strikeCount":            strike_count,
            "includeUnderlyingQuote": "true",
            "strategy":               self.DEFAULT_OPTIONS_STRATEGY,
            "range":                  self.DEFAULT_OPTIONS_RANGE,
            "optionType":             "ALL",
        }
        if expiration is not None:
            params["fromDate"] = expiration
            params["toDate"] = expiration

        headers = {
            "Authorization": f"Bearer {self.credentials.access_token}",
            "Accept": "application/json",
        }

        for attempt in range(2):
            response = httpx.get(
                self.CHAINS_URL,
                headers=headers,
                params=params,
                timeout=15,
            )

            if response.status_code == 200:
                raw = response.json()
                normalized = self._normalize_options_chain(underlying, raw)
                logger.debug(
                    "Fetched options chain for %s — %d expirations, "
                    "%d call strikes, %d put strikes",
                    underlying,
                    len(normalized["expirations"]),
                    sum(len(s) for s in normalized["calls"].values()),
                    sum(len(s) for s in normalized["puts"].values()),
                )
                return normalized

            if response.status_code == 401 and attempt == 0:
                logger.warning(
                    "Schwab chains 401 for %s — refreshing token and retrying",
                    underlying,
                )
                self._refresh_access_token()
                headers["Authorization"] = f"Bearer {self.credentials.access_token}"
                continue

            raise SchwabAPIError(
                f"Schwab /chains returned {response.status_code} "
                f"for {underlying}: {response.text[:200]}"
            )

        raise SchwabAPIError(
            f"Schwab /chains: unexpected control flow for {underlying}"
        )

    def _normalize_options_chain(self, underlying: str, raw: dict) -> dict:
        """Convert Schwab's raw chains response into a normalized dict.

        Schwab returns callExpDateMap/putExpDateMap keyed by
        "YYYY-MM-DD:DTE" with strikes whose values are single-element
        contract lists. We unwrap into {exp_date: {strike_str: contract}}
        and extract the documented field set (see get_options_chain
        docstring for shape).

        Args:
            underlying: Ticker (added to result as-is — Schwab's
                "underlying.symbol" may not always match if it's e.g. an
                index).
            raw: Schwab's response.json().

        Returns:
            Normalized chain dict.
        """
        uq = raw.get("underlying") or {}
        spot = {
            "last":       uq.get("last", 0.0)       or 0.0,
            "bid":        uq.get("bid", 0.0)        or 0.0,
            "ask":        uq.get("ask", 0.0)        or 0.0,
            "mark":       uq.get("mark", 0.0)       or 0.0,
            "volatility": uq.get("volatility", 0.0) or 0.0,
        }
        calls = self._parse_option_exp_map(raw.get("callExpDateMap") or {})
        puts  = self._parse_option_exp_map(raw.get("putExpDateMap")  or {})
        expirations = sorted(set(calls.keys()) | set(puts.keys()))

        return {
            "underlying":  underlying,
            "ts":          time.time(),
            "spot":        spot,
            "calls":       calls,
            "puts":        puts,
            "expirations": expirations,
        }

    def _parse_option_exp_map(self, exp_map: dict) -> dict:
        """Parse Schwab's callExpDateMap/putExpDateMap into a clean dict.

        Schwab keys: "YYYY-MM-DD:DTE" (e.g. "2026-06-19:30"). Strikes are
        keyed by stringified strike ("450.0"), with single-element lists as
        contract values. Malformed keys (missing ":DTE" suffix, or DTE not
        an int) are logged and skipped — defensive against Schwab schema
        drift, but visible so operator can see if Schwab changes format.

        Args:
            exp_map: Schwab's callExpDateMap or putExpDateMap.

        Returns:
            {exp_date_str: {strike_str: contract_dict}} with 12 fields per
            contract (4 prices + 5 greeks + 2 liquidity + dte).
        """
        result: dict = {}
        for exp_key, strikes in exp_map.items():
            try:
                exp_date, dte_str = exp_key.split(":", 1)
                dte = int(dte_str)
            except (ValueError, AttributeError):
                logger.warning("Skipping malformed exp_key: %s", exp_key)
                continue

            result[exp_date] = {}
            for strike_str, contracts in strikes.items():
                if not contracts:
                    continue
                c = contracts[0]  # Schwab nests one contract per strike/exp
                result[exp_date][strike_str] = {
                    "bid":    c.get("bid", 0.0)         or 0.0,
                    "ask":    c.get("ask", 0.0)         or 0.0,
                    "mark":   c.get("mark", 0.0)        or 0.0,
                    "last":   c.get("last", 0.0)        or 0.0,
                    "iv":     c.get("volatility", 0.0)  or 0.0,
                    "delta":  c.get("delta", 0.0)       or 0.0,
                    "gamma":  c.get("gamma", 0.0)       or 0.0,
                    "theta":  c.get("theta", 0.0)       or 0.0,
                    "vega":   c.get("vega", 0.0)        or 0.0,
                    "volume": c.get("totalVolume", 0)   or 0,
                    "oi":     c.get("openInterest", 0)  or 0,
                    "dte":    dte,
                }
        return result

    def get_price_history(
        self,
        symbol: str,
        period_type: str = "month",
        period: int = 1,
        frequency_type: str = "daily",
        frequency: int = 1,
    ) -> list[dict]:
        """Fetch OHLCV candles for a symbol via Schwab Market Data API.

        Pattern ported from Eolo's Bot/marketdata.py (_get_daily_history +
        _fetch_minute_candles). Returns raw candle dicts (no DataFrame
        conversion); SchwabDataLayer (S.5.6e) is responsible for pandas wrapping
        when needed.

        Args:
            symbol: Ticker (e.g. "SPY", "AAPL").
            period_type: "day" | "month" | "year" | "ytd".
            period: How many `period_type` units to fetch.
            frequency_type: "minute" | "daily" | "weekly" | "monthly".
            frequency: Granularity. Valid combinations per Schwab:
                       minute  → 1, 5, 10, 15, 30
                       daily/weekly/monthly → 1
            Defaults yield ~22 daily candles (1 month) — sane default for
            ATHENA Sprint 5 use. Intraday callers must pass explicit kwargs.

        Returns:
            List of candle dicts. Each candle has keys:
                datetime  (int, epoch milliseconds — raw Schwab format)
                open      (float)
                high      (float)
                low       (float)
                close     (float)
                volume    (int)
            Returns [] if Schwab returns no candles (off-hours / unsupported
            symbol / etc. — normal, not an error).

        Raises:
            SchwabAPIError: If Schwab returns non-200 (after one 401 retry), or
                if the response cannot be parsed. Network errors propagate
                natively (httpx.RequestError).
            SchwabAuthError: If the 401 retry's _refresh_access_token also fails.

        Notes:
            - Schwab caps intraday: `period_type="day"` accepts period 1-10.
              Invalid combos → SchwabAPIError from Schwab's 400.
            - No tail trimming. Caller takes the slice they need.
            - 401 retry: max 1 attempt with explicit _refresh_access_token in
              between (Schwab's token may have just expired despite our 60s
              expiry buffer).
        """
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        params = {
            "symbol": symbol,
            "periodType": period_type,
            "period": period,
            "frequencyType": frequency_type,
            "frequency": frequency,
            "needExtendedHoursData": False,
        }
        headers = {"Authorization": f"Bearer {self.credentials.access_token}"}

        for attempt in range(2):
            response = httpx.get(
                self.PRICE_HISTORY_URL,
                headers=headers,
                params=params,
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                candles = data.get("candles", [])
                if not candles:
                    logger.debug(
                        "Schwab pricehistory returned no candles for %s "
                        "(%s/%d %s/%d)",
                        symbol, period_type, period, frequency_type, frequency,
                    )
                    return []
                logger.debug(
                    "Fetched %d candles for %s (%s/%d %s/%d)",
                    len(candles), symbol, period_type, period,
                    frequency_type, frequency,
                )
                return candles

            if response.status_code == 401 and attempt == 0:
                logger.warning(
                    "Schwab pricehistory 401 for %s — refreshing token and retrying",
                    symbol,
                )
                self._refresh_access_token()
                headers = {"Authorization": f"Bearer {self.credentials.access_token}"}
                continue

            # Non-200 (or 401 on second attempt) — not retryable.
            raise SchwabAPIError(
                f"Schwab /pricehistory returned {response.status_code} "
                f"for {symbol}: {response.text[:200]}"
            )

        # Unreachable: loop always exits via return or raise.
        raise SchwabAPIError(
            f"Schwab /pricehistory: unexpected control flow for {symbol}"
        )

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
