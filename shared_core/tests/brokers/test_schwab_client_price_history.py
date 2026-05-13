"""
Unit tests for SchwabClient.get_price_history.

Mocking strategy:
    - httpx.get patched at the schwab_client module level.
    - _refresh_access_token patched as MagicMock on the instance (so 401 retry
      tests can verify the call without triggering the real refresh flow).
    - _ensure_authenticated is left intact but harmless: the test client
      ships with credentials.access_token preset so the auth check is a no-op.

Helper factory `_build_client_with_price_history_mocks()` is a contextmanager
yielding (client, mock_httpx_get, mock_refresh).
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

import pytest

from shared_core.brokers.schwab_client import (
    SchwabAPIError,
    SchwabClient,
    SchwabCredentials,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_CANDLES = [
    {"datetime": 1714867200000, "open": 100.5, "high": 102.1,
     "low":  99.8,  "close": 101.7, "volume": 1234567},
    {"datetime": 1714953600000, "open": 101.7, "high": 103.5,
     "low": 101.2,  "close": 103.0, "volume": 1100000},
    {"datetime": 1715040000000, "open": 103.0, "high": 103.8,
     "low": 102.4,  "close": 102.8, "volume": 950000},
]

_SCHWAB_HISTORY_RESPONSE = {
    "candles": _SAMPLE_CANDLES,
    "symbol": "SPY",
    "empty": False,
}


@contextmanager
def _build_client_with_price_history_mocks(
    *,
    schwab_status: int = 200,
    schwab_body: dict | None = None,
    second_attempt_status: int | None = None,
    second_attempt_body: dict | None = None,
):
    """Build a SchwabClient with httpx.get patched and _refresh_access_token
    stubbed as a MagicMock.

    Single-response mode (default): httpx.get always returns the same response.
    Two-response mode (when `second_attempt_status` is not None): the first
    call returns (schwab_status, schwab_body), the second returns
    (second_attempt_status, second_attempt_body). Used for the 401-retry tests.

    Yields:
        (client, mock_httpx_get, mock_refresh)
    """
    if schwab_body is None:
        schwab_body = dict(_SCHWAB_HISTORY_RESPONSE)

    def _make_resp(status: int, body: dict) -> MagicMock:
        r = MagicMock()
        r.status_code = status
        r.json.return_value = body
        r.text = str(body)
        return r

    if second_attempt_status is None:
        side_effect = None
        return_value = _make_resp(schwab_status, schwab_body)
    else:
        second_body = second_attempt_body if second_attempt_body is not None else dict(_SCHWAB_HISTORY_RESPONSE)
        side_effect = [
            _make_resp(schwab_status, schwab_body),
            _make_resp(second_attempt_status, second_body),
        ]
        return_value = None

    with ExitStack() as stack:
        mock_get = stack.enter_context(patch(
            "shared_core.brokers.schwab_client.httpx.get",
        ))
        if side_effect is not None:
            mock_get.side_effect = side_effect
        else:
            mock_get.return_value = return_value

        # Pre-authenticated client: skip the real OAuth refresh in _ensure_authenticated.
        creds = SchwabCredentials(
            api_key="ak",
            api_secret="as",
            access_token="initial_access_token",
            token_expires_at=9_999_999_999.0,  # far future → _ensure_authenticated is a no-op
        )
        client = SchwabClient(credentials=creds, paper_trading=True)

        # Stub _refresh_access_token so tests don't hit GCP. The stub also
        # rotates the in-memory access_token so the post-401 retry's Bearer
        # header reflects the "new" token.
        def _fake_refresh() -> None:
            client.credentials.access_token = "refreshed_access_token"
        client._refresh_access_token = MagicMock(side_effect=_fake_refresh)
        mock_refresh = client._refresh_access_token

        yield client, mock_get, mock_refresh


# ── TestGetPriceHistorySuccess ────────────────────────────────────────────────

class TestGetPriceHistorySuccess:

    def test_returns_candles_list_unchanged(self):
        with _build_client_with_price_history_mocks() as (client, *_):
            result = client.get_price_history("SPY")
            assert result == _SAMPLE_CANDLES

    def test_includes_required_query_params(self):
        with _build_client_with_price_history_mocks() as (client, mock_get, _):
            client.get_price_history(
                "AAPL",
                period_type="day",
                period=5,
                frequency_type="minute",
                frequency=5,
            )
            params = mock_get.call_args.kwargs["params"]
            assert params["symbol"] == "AAPL"
            assert params["periodType"] == "day"
            assert params["period"] == 5
            assert params["frequencyType"] == "minute"
            assert params["frequency"] == 5

    def test_uses_pricehistory_url(self):
        with _build_client_with_price_history_mocks() as (client, mock_get, _):
            client.get_price_history("SPY")
            args, _ = mock_get.call_args
            assert args[0] == "https://api.schwabapi.com/marketdata/v1/pricehistory"

    def test_sets_bearer_auth_header(self):
        with _build_client_with_price_history_mocks() as (client, mock_get, _):
            client.get_price_history("SPY")
            headers = mock_get.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer initial_access_token"

    def test_returns_empty_list_when_no_candles(self):
        with _build_client_with_price_history_mocks(
            schwab_body={"candles": [], "symbol": "SPY", "empty": True},
        ) as (client, *_):
            result = client.get_price_history("SPY")
            assert result == []

    def test_needExtendedHoursData_is_false(self):
        with _build_client_with_price_history_mocks() as (client, mock_get, _):
            client.get_price_history("SPY")
            params = mock_get.call_args.kwargs["params"]
            assert params["needExtendedHoursData"] is False

    def test_datetime_is_int_epoch_ms(self):
        # Invariant: shared_core returns raw Schwab format (epoch ms int),
        # no datetime conversion. SchwabDataLayer wraps with pandas later.
        with _build_client_with_price_history_mocks() as (client, *_):
            result = client.get_price_history("SPY")
            assert all(isinstance(c["datetime"], int) for c in result)
            assert result[0]["datetime"] == 1714867200000


# ── TestGetPriceHistoryErrorPaths ─────────────────────────────────────────────

class TestGetPriceHistoryErrorPaths:

    def test_raises_schwab_api_error_on_400(self):
        with _build_client_with_price_history_mocks(
            schwab_status=400,
            schwab_body={"error": "invalid period"},
        ) as (client, *_):
            with pytest.raises(SchwabAPIError, match="400"):
                client.get_price_history("SPY", period_type="day", period=30)

    def test_raises_schwab_api_error_on_500(self):
        with _build_client_with_price_history_mocks(
            schwab_status=500,
            schwab_body={"error": "internal"},
        ) as (client, *_):
            with pytest.raises(SchwabAPIError, match="500"):
                client.get_price_history("SPY")

    def test_does_not_retry_on_non_401_error(self):
        # Non-401 errors should NOT trigger _refresh_access_token. They raise
        # immediately on the first attempt.
        with _build_client_with_price_history_mocks(
            schwab_status=403,
            schwab_body={"error": "forbidden"},
        ) as (client, mock_get, mock_refresh):
            with pytest.raises(SchwabAPIError):
                client.get_price_history("SPY")
            mock_refresh.assert_not_called()
            assert mock_get.call_count == 1


# ── TestGetPriceHistory401Retry ───────────────────────────────────────────────

class TestGetPriceHistory401Retry:

    def test_401_first_attempt_triggers_refresh_and_retries(self):
        with _build_client_with_price_history_mocks(
            schwab_status=401,
            schwab_body={"error": "expired"},
            second_attempt_status=200,
            second_attempt_body=_SCHWAB_HISTORY_RESPONSE,
        ) as (client, mock_get, mock_refresh):
            result = client.get_price_history("SPY")
            assert result == _SAMPLE_CANDLES
            mock_refresh.assert_called_once()
            assert mock_get.call_count == 2

    def test_401_persists_raises_schwab_api_error(self):
        # Both attempts return 401 → SchwabAPIError on the second, refresh
        # called exactly once (between the two attempts).
        with _build_client_with_price_history_mocks(
            schwab_status=401,
            schwab_body={"error": "expired"},
            second_attempt_status=401,
            second_attempt_body={"error": "still expired"},
        ) as (client, mock_get, mock_refresh):
            with pytest.raises(SchwabAPIError, match="401"):
                client.get_price_history("SPY")
            mock_refresh.assert_called_once()
            assert mock_get.call_count == 2

    def test_uses_new_token_after_refresh(self):
        # The Bearer header on the retry must use the refreshed access_token,
        # not the stale one. _fake_refresh rotates to "refreshed_access_token".
        with _build_client_with_price_history_mocks(
            schwab_status=401,
            schwab_body={"error": "expired"},
            second_attempt_status=200,
            second_attempt_body=_SCHWAB_HISTORY_RESPONSE,
        ) as (client, mock_get, _):
            client.get_price_history("SPY")
            first_call_headers = mock_get.call_args_list[0].kwargs["headers"]
            second_call_headers = mock_get.call_args_list[1].kwargs["headers"]
            assert first_call_headers["Authorization"] == "Bearer initial_access_token"
            assert second_call_headers["Authorization"] == "Bearer refreshed_access_token"
