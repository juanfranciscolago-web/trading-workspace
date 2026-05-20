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
    retrieve_firestore_dict,
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


def _normalize_position(raw: dict) -> dict:
    """Normalize Schwab position dict to multi-agent canonical shape.

    ADR-013 D-δ: quantity = longQuantity - shortQuantity (signed convention).
    ADR-013 D-γ: asset class agnostic, OPTION-specific fields conditional.

    Args:
        raw: Schwab API position dict from securitiesAccount.positions[].

    Returns:
        Normalized dict con keys: symbol, asset_class, quantity (signed),
        average_price, market_value, unrealized_pnl. Plus OPTION-specific
        (option_type, strike, expiration) si assetType == "OPTION".
    """
    instrument = raw.get("instrument", {})
    asset_type = instrument.get("assetType", "UNKNOWN")

    long_qty = float(raw.get("longQuantity", 0))
    short_qty = float(raw.get("shortQuantity", 0))
    quantity = long_qty - short_qty

    normalized = {
        "symbol": instrument.get("symbol", ""),
        "asset_class": asset_type,
        "quantity": quantity,
        "average_price": float(raw.get("averagePrice", 0)),
        "market_value": float(raw.get("marketValue", 0)),
        "unrealized_pnl": float(raw.get("currentDayProfitLoss", 0)),
    }

    if asset_type == "OPTION":
        normalized["option_type"] = instrument.get("putCall", "")  # "PUT" or "CALL"
        normalized["strike"] = float(instrument.get("strikePrice", 0))
        normalized["expiration"] = instrument.get("expirationDate", "")

    return normalized


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
    TRADER_BASE_URL = "https://api.schwabapi.com/trader/v1"
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
        account_id: str | None = None,
    ):
        """Init SchwabClient.

        Args:
            credentials: SchwabCredentials with api_key/api_secret + tokens.
            paper_trading: True (default) for paper subaccount, False for live.
            rate_limit_per_second: RateLimiter throttle (default 5/sec Schwab cap).
            account_id: Optional Schwab account number explicit (ADR-013 D9 + D9-1).
                If None (default), get_account_id() auto-discovers via GET
                /trader/v1/accounts picking first (Eolo behavior). If set,
                multi-agent uses specified subaccount (D9 isolation, no Eolo
                conflation).
        """
        self.credentials = credentials
        self.paper_trading = paper_trading
        self.rate_limiter = RateLimiter(rate_limit_per_second)
        self._http_client = None  # Initialize lazily
        # ADR-013 D9-1: cached explicit account_id (None until discovered).
        self._account_id: str | None = account_id
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

    @classmethod
    def from_gcp(
        cls,
        *,
        paper_trading: bool = True,
        rate_limit_per_second: int = 5,
        account_id: str | None = None,
    ) -> "SchwabClient":
        """Construct SchwabClient using GCP-backed credentials.

        Reads:
        - app_key + app_secret from Secret Manager (cs-app-key).
        - access_token + refresh_token from Firestore
          (schwab-tokens/schwab-tokens-auth).

        This is the canonical factory post-S.5.6b. Use this instead of
        from_env() — `_refresh_access_token` (S.5.6b) reads app credentials
        from Secret Manager and refresh_token from Firestore, NOT from the
        SchwabCredentials.api_key / api_secret / refresh_token fields. So
        from_env's env-var-loaded credentials are vestigial at runtime;
        from_gcp avoids requiring SCHWAB_API_KEY/SECRET env vars entirely.

        Note on token_expires_at: Schwab's /oauth/token response includes
        `expires_in` (relative seconds) but NOT an absolute timestamp.
        S.5.6b's _refresh_access_token computes absolute expiry only
        in-memory after each refresh; the value stored to Firestore is the
        raw Schwab response (relative). from_gcp therefore initializes
        token_expires_at=None, which causes _ensure_authenticated to skip
        its proactive 60s-before-expiry check. If the loaded access_token
        is stale, the first Schwab call returns 401 and the 401-retry path
        in get_price_history / get_options_chain handles refresh. Adding
        a _persisted_at field in S.5.6b's Firestore write is registered
        as Sprint 6+ tech debt.

        Raises:
            SchwabAuthError: If Firestore lacks the token document
                (operator must run safe_init_auth_v2.py once to bootstrap).
            google.api_core.exceptions.NotFound: If cs-app-key secret does
                not exist in Secret Manager.
            KeyError: If cs-app-key payload lacks `app-key` or `app-secret`.
        """
        app_creds = retrieve_google_secret_dict(
            gcp_id=cls.GCP_PROJECT_ID,
            secret_id=cls.APP_KEY_SECRET_ID,
        )
        tokens = retrieve_firestore_dict(
            collection_id=cls.TOKEN_COLLECTION,
            document_id=cls.TOKEN_DOCUMENT,
            project_id=cls.GCP_PROJECT_ID,
        )
        if tokens is None:
            raise SchwabAuthError(
                f"No tokens in Firestore "
                f"{cls.TOKEN_COLLECTION}/{cls.TOKEN_DOCUMENT}. "
                f"Run safe_init_auth_v2.py to bootstrap."
            )

        creds = SchwabCredentials(
            api_key=app_creds["app-key"],
            api_secret=app_creds["app-secret"],
            access_token=tokens.get("access_token"),
            refresh_token=tokens.get("refresh_token"),
            token_expires_at=None,
        )
        return cls(
            credentials=creds,
            paper_trading=paper_trading,
            rate_limit_per_second=rate_limit_per_second,
            account_id=account_id,
        )

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

    def get_account_id(self) -> str:
        """Return cached account_id or discover via GET /trader/v1/accounts.

        ADR-013 D9 + D9-1: If account_id was set explicit en __init__ (multi-agent
        subaccount isolation), return cached value. Otherwise discover via Schwab
        API picking first account (Eolo behavior preserved for default deployments).

        Pattern ported from Eolo's options_trader.py get_account_id() — adapted to
        httpx (vs requests) + SchwabAPIError (vs ValueError) for SchwabClient
        contract consistency.

        Returns:
            Schwab account number (string).

        Raises:
            SchwabAPIError: si HTTP non-200, empty accounts list, o missing
                accountNumber field.
            SchwabAuthError: si 401 retry path's _refresh_access_token also fails.
        """
        if self._account_id is not None:
            return self._account_id

        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        url = f"{self.TRADER_BASE_URL}/accounts"
        headers = {"Authorization": f"Bearer {self.credentials.access_token}"}

        for attempt in range(2):  # ADR-013 D-ε: 401 retry pattern
            try:
                response = httpx.get(url, headers=headers, timeout=10)
            except httpx.RequestError as e:
                raise SchwabAPIError(f"get_account_id request failed: {e}") from e

            if response.status_code == 401 and attempt == 0:
                logger.warning("Schwab /accounts 401 — refreshing token and retrying")
                self._refresh_access_token()
                headers = {"Authorization": f"Bearer {self.credentials.access_token}"}
                continue

            if response.status_code != 200:
                raise SchwabAPIError(
                    f"get_account_id: HTTP {response.status_code} — {response.text[:200]}"
                )

            accounts = response.json()
            if not accounts or not isinstance(accounts, list):
                raise SchwabAPIError(
                    f"get_account_id: empty or invalid accounts response: {accounts!r}"
                )

            first = accounts[0]
            sa = first.get("securitiesAccount", {})
            account_number = sa.get("accountNumber")
            if not account_number:
                raise SchwabAPIError(
                    f"get_account_id: missing accountNumber in {first!r}"
                )

            self._account_id = str(account_number)
            logger.info("Schwab account discovered: %s", self._account_id)
            return self._account_id

        raise SchwabAPIError("get_account_id: exhausted retries")  # defensive

    def get_positions(self) -> list[dict]:
        """Return normalized positions list for cached/discovered account.

        ADR-013 D-γ agnostic: NO OPTION-only filter (vs Eolo). Returns ALL asset
        classes — equities, options, futures, etc. ATLAS PositionView validates
        per asset_class downstream (separation of concerns).

        ADR-013 D-δ signed quantity: quantity = longQuantity - shortQuantity
        (Schwab returns both as positive; signed convention aligns con PositionView).

        Pattern ported from Eolo's options_trader.py get_positions() — adapted to
        sync httpx + asset-class-agnostic normalization.

        Returns:
            List of dicts con normalized keys: symbol, asset_class, quantity
            (signed), average_price, market_value, unrealized_pnl. Option-specific
            keys (option_type, strike, expiration) conditional si OPTION.
            Empty list si no positions.

        Raises:
            SchwabAPIError: si HTTP error o malformed response.
            SchwabAuthError: si 401 retry path fails.
        """
        account_id = self.get_account_id()
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        url = f"{self.TRADER_BASE_URL}/accounts/{account_id}"
        params = {"fields": "positions"}
        headers = {"Authorization": f"Bearer {self.credentials.access_token}"}

        for attempt in range(2):  # ADR-013 D-ε: 401 retry pattern
            try:
                response = httpx.get(url, headers=headers, params=params, timeout=10)
            except httpx.RequestError as e:
                raise SchwabAPIError(f"get_positions request failed: {e}") from e

            if response.status_code == 401 and attempt == 0:
                logger.warning("Schwab /accounts/%s 401 — refreshing token and retrying", account_id)
                self._refresh_access_token()
                headers = {"Authorization": f"Bearer {self.credentials.access_token}"}
                continue

            if response.status_code != 200:
                raise SchwabAPIError(
                    f"get_positions: HTTP {response.status_code} — {response.text[:200]}"
                )

            data = response.json()
            sa = data.get("securitiesAccount", {})
            positions_raw = sa.get("positions", [])

            return [_normalize_position(p) for p in positions_raw]

        raise SchwabAPIError("get_positions: exhausted retries")  # defensive

    def get_balances(self) -> dict:
        """Return normalized account balances dict.

        ADR-013 D5-C: separate endpoint GET /trader/v1/accounts/{id} (no fields
        param). Parse securitiesAccount.currentBalances → 5-key dict normalized.

        NO Eolo precedent (F-r2 ADR-013 catch). Schwab API docs source. Field
        names per Schwab documentation; verification deferred to integration test
        gate (Sprint 11+ production runs).

        ADR-013 D-ζ defensive float conversion: float(value or 0) handles both
        missing keys and explicit None values from Schwab response.

        Returns:
            Dict with 5 keys (all float):
            - cash: cashBalance from Schwab response.
            - buying_power: buyingPower.
            - total_value: liquidationValue.
            - margin_used: marginBalance.
            - day_trading_buying_power: dayTradingBuyingPower.

        Raises:
            SchwabAPIError: si HTTP error o malformed response.
            SchwabAuthError: si 401 retry path's _refresh_access_token fails.
        """
        account_id = self.get_account_id()
        self._ensure_authenticated()
        self.rate_limiter.wait_if_needed()

        url = f"{self.TRADER_BASE_URL}/accounts/{account_id}"
        headers = {"Authorization": f"Bearer {self.credentials.access_token}"}

        for attempt in range(2):  # ADR-013 D-ε: 401 retry pattern
            try:
                response = httpx.get(url, headers=headers, timeout=10)
            except httpx.RequestError as e:
                raise SchwabAPIError(f"get_balances request failed: {e}") from e

            if response.status_code == 401 and attempt == 0:
                logger.warning(
                    "Schwab /accounts/%s 401 — refreshing token and retrying",
                    account_id,
                )
                self._refresh_access_token()
                headers = {"Authorization": f"Bearer {self.credentials.access_token}"}
                continue

            if response.status_code != 200:
                raise SchwabAPIError(
                    f"get_balances: HTTP {response.status_code} — {response.text[:200]}"
                )

            data = response.json()
            sa = data.get("securitiesAccount", {})
            balances = sa.get("currentBalances", {})

            # ADR-013 D-ζ: defensive None-coalesce float conversion.
            return {
                "cash": float(balances.get("cashBalance") or 0),
                "buying_power": float(balances.get("buyingPower") or 0),
                "total_value": float(balances.get("liquidationValue") or 0),
                "margin_used": float(balances.get("marginBalance") or 0),
                "day_trading_buying_power": float(
                    balances.get("dayTradingBuyingPower") or 0
                ),
            }

        raise SchwabAPIError("get_balances: exhausted retries")  # defensive

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
