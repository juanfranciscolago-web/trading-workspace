"""
Unit tests for SchwabClient.get_options_chain.

Mocking strategy mirrors test_schwab_client_price_history.py:
    - httpx.get patched at the schwab_client module level.
    - _refresh_access_token stubbed as MagicMock on the instance.
    - Pre-authenticated client (access_token preset + token_expires_at
      far future) → _ensure_authenticated is a no-op.

Helper factory `_build_client_with_chain_mocks()` supports dual mode
(single-response default + two-response side_effect for retry tests).
"""
from __future__ import annotations

import copy
import logging
from contextlib import ExitStack, contextmanager
from unittest.mock import MagicMock, patch

import pytest

from shared_core.brokers.schwab_client import (
    SchwabAPIError,
    SchwabClient,
    SchwabCredentials,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_SCHWAB_CHAIN_RESPONSE = {
    "underlying": {
        "last": 450.0, "bid": 449.95, "ask": 450.05, "mark": 450.0,
        "volatility": 0.18,
    },
    "callExpDateMap": {
        "2026-06-19:30": {
            "450.0": [{
                "bid": 5.0, "ask": 5.20, "mark": 5.10, "last": 5.12,
                "volatility": 0.20, "delta": 0.50, "gamma": 0.05,
                "theta": -0.04, "vega": 0.12,
                "totalVolume": 1500, "openInterest": 8000,
            }],
            "455.0": [{
                "bid": 2.50, "ask": 2.65, "mark": 2.575, "last": 2.55,
                "volatility": 0.22, "delta": 0.30, "gamma": 0.04,
                "theta": -0.05, "vega": 0.10,
                "totalVolume": 800, "openInterest": 4000,
            }],
        },
        "2026-07-17:58": {
            "450.0": [{
                "bid": 8.50, "ask": 8.75, "mark": 8.625, "last": 8.60,
                "volatility": 0.21, "delta": 0.52, "gamma": 0.03,
                "theta": -0.03, "vega": 0.18,
                "totalVolume": 600, "openInterest": 2500,
            }],
        },
    },
    "putExpDateMap": {
        "2026-06-19:30": {
            "450.0": [{
                "bid": 4.80, "ask": 5.00, "mark": 4.90, "last": 4.95,
                "volatility": 0.21, "delta": -0.50, "gamma": 0.05,
                "theta": -0.04, "vega": 0.12,
                "totalVolume": 1200, "openInterest": 6000,
            }],
        },
    },
    "status": "SUCCESS",
}


@contextmanager
def _build_client_with_chain_mocks(
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
    (second_attempt_status, second_attempt_body).

    Yields:
        (client, mock_httpx_get, mock_refresh)
    """
    if schwab_body is None:
        schwab_body = copy.deepcopy(_SCHWAB_CHAIN_RESPONSE)

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
        second_body = (
            second_attempt_body if second_attempt_body is not None
            else copy.deepcopy(_SCHWAB_CHAIN_RESPONSE)
        )
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

        creds = SchwabCredentials(
            api_key="ak",
            api_secret="as",
            access_token="initial_access_token",
            token_expires_at=9_999_999_999.0,  # far future → _ensure_authenticated no-op
        )
        client = SchwabClient(credentials=creds, paper_trading=True)

        def _fake_refresh() -> None:
            client.credentials.access_token = "refreshed_access_token"
        client._refresh_access_token = MagicMock(side_effect=_fake_refresh)

        yield client, mock_get, client._refresh_access_token


# ── TestGetOptionsChainSuccess ────────────────────────────────────────────────

class TestGetOptionsChainSuccess:

    def test_returns_normalized_chain_dict(self):
        with _build_client_with_chain_mocks() as (client, *_):
            result = client.get_options_chain("SPY")
            assert set(result.keys()) == {
                "underlying", "ts", "spot", "calls", "puts", "expirations",
            }
            assert result["underlying"] == "SPY"
            assert isinstance(result["ts"], float)

    def test_includes_required_query_params(self):
        with _build_client_with_chain_mocks() as (client, mock_get, _):
            client.get_options_chain("AAPL", strike_count=15)
            params = mock_get.call_args.kwargs["params"]
            assert params["symbol"] == "AAPL"
            assert params["contractType"] == "ALL"
            assert params["strikeCount"] == 15
            assert params["strategy"] == "SINGLE"
            assert params["range"] == "ALL"
            assert params["includeUnderlyingQuote"] == "true"
            assert params["optionType"] == "ALL"

    def test_uses_chains_url(self):
        with _build_client_with_chain_mocks() as (client, mock_get, _):
            client.get_options_chain("SPY")
            args, _ = mock_get.call_args
            assert args[0] == "https://api.schwabapi.com/marketdata/v1/chains"

    def test_sets_bearer_auth_header_and_accept(self):
        with _build_client_with_chain_mocks() as (client, mock_get, _):
            client.get_options_chain("SPY")
            headers = mock_get.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bearer initial_access_token"
            assert headers["Accept"] == "application/json"

    def test_strike_count_param_passes_through(self):
        with _build_client_with_chain_mocks() as (client, mock_get, _):
            client.get_options_chain("SPY", strike_count=5)
            assert mock_get.call_args.kwargs["params"]["strikeCount"] == 5


# ── TestExpirationFilter ──────────────────────────────────────────────────────

class TestExpirationFilter:

    def test_expiration_none_omits_date_params(self):
        with _build_client_with_chain_mocks() as (client, mock_get, _):
            client.get_options_chain("SPY", expiration=None)
            params = mock_get.call_args.kwargs["params"]
            assert "fromDate" not in params
            assert "toDate" not in params

    def test_expiration_provided_sets_fromDate_and_toDate(self):
        with _build_client_with_chain_mocks() as (client, mock_get, _):
            client.get_options_chain("SPY", expiration="2026-06-19")
            params = mock_get.call_args.kwargs["params"]
            assert params["fromDate"] == "2026-06-19"
            assert params["toDate"] == "2026-06-19"

    def test_expiration_filter_propagates_to_normalization(self):
        # Single-expiration response → result["expirations"] has 1 element.
        single_exp_body = {
            "underlying": {"last": 450.0, "bid": 449.95, "ask": 450.05,
                           "mark": 450.0, "volatility": 0.18},
            "callExpDateMap": {
                "2026-06-19:30": {
                    "450.0": [{
                        "bid": 5.0, "ask": 5.2, "mark": 5.1, "last": 5.12,
                        "volatility": 0.2, "delta": 0.5, "gamma": 0.05,
                        "theta": -0.04, "vega": 0.12,
                        "totalVolume": 1500, "openInterest": 8000,
                    }]
                }
            },
            "putExpDateMap": {},
        }
        with _build_client_with_chain_mocks(schwab_body=single_exp_body) as (client, *_):
            result = client.get_options_chain("SPY", expiration="2026-06-19")
            assert result["expirations"] == ["2026-06-19"]


# ── TestNormalizeOptionsChain ────────────────────────────────────────────────

class TestNormalizeOptionsChain:

    def test_spot_fields_extracted_from_underlying(self):
        with _build_client_with_chain_mocks() as (client, *_):
            result = client.get_options_chain("SPY")
            spot = result["spot"]
            assert spot["last"] == 450.0
            assert spot["bid"] == 449.95
            assert spot["ask"] == 450.05
            assert spot["mark"] == 450.0
            assert spot["volatility"] == 0.18

    def test_calls_and_puts_parsed_from_exp_date_maps(self):
        with _build_client_with_chain_mocks() as (client, *_):
            result = client.get_options_chain("SPY")
            # Calls 450 at 2026-06-19: 12 fields, including renames.
            call = result["calls"]["2026-06-19"]["450.0"]
            assert set(call.keys()) == {
                "bid", "ask", "mark", "last",
                "iv", "delta", "gamma", "theta", "vega",
                "volume", "oi", "dte",
            }
            assert call["bid"] == 5.0
            assert call["ask"] == 5.20
            assert call["iv"] == 0.20            # Schwab "volatility" → iv
            assert call["volume"] == 1500        # Schwab "totalVolume" → volume
            assert call["oi"] == 8000            # Schwab "openInterest" → oi
            # Puts 450 at 2026-06-19
            put = result["puts"]["2026-06-19"]["450.0"]
            assert put["bid"] == 4.80
            assert put["delta"] == -0.50

    def test_dte_computed_from_exp_key(self):
        with _build_client_with_chain_mocks() as (client, *_):
            result = client.get_options_chain("SPY")
            assert result["calls"]["2026-06-19"]["450.0"]["dte"] == 30
            assert result["calls"]["2026-07-17"]["450.0"]["dte"] == 58

    def test_expirations_sorted_ascending(self):
        with _build_client_with_chain_mocks() as (client, *_):
            result = client.get_options_chain("SPY")
            assert result["expirations"] == ["2026-06-19", "2026-07-17"]

    def test_defaults_zero_for_missing_numeric_fields(self):
        # Strikes missing greeks → fields default to 0.0.
        body_with_missing = {
            "underlying": {"last": 450.0},   # bid, ask, mark, volatility missing
            "callExpDateMap": {
                "2026-06-19:30": {
                    "450.0": [{"bid": 5.0}]   # ask, mark, last, IV, greeks all missing
                }
            },
            "putExpDateMap": {},
        }
        with _build_client_with_chain_mocks(schwab_body=body_with_missing) as (client, *_):
            result = client.get_options_chain("SPY")
            # Spot defaults
            assert result["spot"]["bid"] == 0.0
            assert result["spot"]["volatility"] == 0.0
            # Call defaults (greeks all missing → 0.0)
            call = result["calls"]["2026-06-19"]["450.0"]
            assert call["bid"] == 5.0       # present
            assert call["ask"] == 0.0       # missing
            assert call["delta"] == 0.0     # missing
            assert call["iv"] == 0.0        # missing
            assert call["volume"] == 0      # int default
            assert call["oi"] == 0          # int default


# ── TestMalformedExpKey ───────────────────────────────────────────────────────

class TestMalformedExpKey:

    def test_malformed_exp_key_logs_warning_and_skips(self, caplog):
        # Direct invocation of _parse_option_exp_map with ad-hoc exp_map.
        creds = SchwabCredentials(api_key="ak", api_secret="as")
        client = SchwabClient(credentials=creds)
        exp_map = {
            "no-colon-here": {"450.0": [{"bid": 1.0}]},
            "2026-06-19:not-an-int": {"450.0": [{"bid": 2.0}]},
        }
        with caplog.at_level(logging.WARNING, logger="shared_core.brokers.schwab_client"):
            result = client._parse_option_exp_map(exp_map)
        assert result == {}
        assert any("Skipping malformed exp_key" in r.message for r in caplog.records)

    def test_partial_malformed_does_not_block_valid_entries(self, caplog):
        creds = SchwabCredentials(api_key="ak", api_secret="as")
        client = SchwabClient(credentials=creds)
        exp_map = {
            "malformed-key": {"450.0": [{"bid": 1.0}]},
            "2026-06-19:30": {"450.0": [{"bid": 5.0, "ask": 5.2}]},
        }
        with caplog.at_level(logging.WARNING, logger="shared_core.brokers.schwab_client"):
            result = client._parse_option_exp_map(exp_map)
        assert "2026-06-19" in result
        assert result["2026-06-19"]["450.0"]["bid"] == 5.0
        assert "malformed-key" not in result


# ── TestGetOptionsChainErrorPaths ─────────────────────────────────────────────

class TestGetOptionsChainErrorPaths:

    def test_raises_schwab_api_error_on_400(self):
        with _build_client_with_chain_mocks(
            schwab_status=400,
            schwab_body={"error": "invalid symbol"},
        ) as (client, *_):
            with pytest.raises(SchwabAPIError, match="400"):
                client.get_options_chain("INVALID")

    def test_raises_schwab_api_error_on_500(self):
        with _build_client_with_chain_mocks(
            schwab_status=500,
            schwab_body={"error": "internal"},
        ) as (client, *_):
            with pytest.raises(SchwabAPIError, match="500"):
                client.get_options_chain("SPY")

    def test_does_not_retry_on_non_401_error(self):
        with _build_client_with_chain_mocks(
            schwab_status=403,
            schwab_body={"error": "forbidden"},
        ) as (client, mock_get, mock_refresh):
            with pytest.raises(SchwabAPIError):
                client.get_options_chain("SPY")
            mock_refresh.assert_not_called()
            assert mock_get.call_count == 1


# ── TestGetOptionsChain401Retry ───────────────────────────────────────────────

class TestGetOptionsChain401Retry:

    def test_401_first_attempt_triggers_refresh_and_retries(self):
        with _build_client_with_chain_mocks(
            schwab_status=401,
            schwab_body={"error": "expired"},
            second_attempt_status=200,
            second_attempt_body=_SCHWAB_CHAIN_RESPONSE,
        ) as (client, mock_get, mock_refresh):
            result = client.get_options_chain("SPY")
            assert result["underlying"] == "SPY"
            mock_refresh.assert_called_once()
            assert mock_get.call_count == 2

    def test_401_persists_raises_schwab_api_error(self):
        with _build_client_with_chain_mocks(
            schwab_status=401,
            schwab_body={"error": "expired"},
            second_attempt_status=401,
            second_attempt_body={"error": "still expired"},
        ) as (client, mock_get, mock_refresh):
            with pytest.raises(SchwabAPIError, match="401"):
                client.get_options_chain("SPY")
            mock_refresh.assert_called_once()
            assert mock_get.call_count == 2
