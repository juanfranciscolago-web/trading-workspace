"""Unit tests for SchwabClient.get_balances (S.11.atlas-c).

Covers ADR-013 D5-C (separate endpoint) + D-ε (401 retry) + D-ζ (defensive
float None-coalesce). NO Eolo precedent (F-r2 ADR-013).
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest

from shared_core.brokers.schwab_client import (
    SchwabAPIError,
    SchwabClient,
    SchwabCredentials,
)


def _make_resp(status_code: int, body) -> MagicMock:
    """Mock httpx.Response factory."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.text = str(body)
    return resp


@contextmanager
def _build_client(account_id: str | None = None):
    """Helper: build SchwabClient with mocked auth + rate_limiter."""
    credentials = SchwabCredentials(
        api_key="test_key",
        api_secret="test_secret",
        access_token="test_token",
        refresh_token="test_refresh",
    )
    client = SchwabClient(
        credentials,
        paper_trading=True,
        rate_limit_per_second=100,
        account_id=account_id,
    )
    client._refresh_access_token = MagicMock()
    client.rate_limiter.wait_if_needed = MagicMock()
    yield client


# ── TestGetBalances (11 tests) ─────────────────────────────────────────────────


class TestGetBalances:
    """get_balances() — ADR-013 D5-C + D-ε + D-ζ."""

    def test_returns_normalized_dict(self):
        """D5-C basic: 5 keys present con valores correct."""
        with _build_client(account_id="acct_123") as client:
            balances_body = {
                "securitiesAccount": {
                    "currentBalances": {
                        "cashBalance": 50000.0,
                        "buyingPower": 100000.0,
                        "liquidationValue": 150000.0,
                        "marginBalance": 25000.0,
                        "dayTradingBuyingPower": 200000.0,
                    }
                }
            }
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, balances_body),
            ):
                result = client.get_balances()
            assert result["cash"] == 50000.0
            assert result["buying_power"] == 100000.0
            assert result["total_value"] == 150000.0
            assert result["margin_used"] == 25000.0
            assert result["day_trading_buying_power"] == 200000.0
            assert set(result.keys()) == {
                "cash", "buying_power", "total_value",
                "margin_used", "day_trading_buying_power",
            }

    def test_uses_explicit_account_id_no_discovery(self):
        """D-α + D9-1: account_id set en __init__ skips discovery API call."""
        with _build_client(account_id="explicit_999") as client:
            mock_resp = _make_resp(200, {"securitiesAccount": {"currentBalances": {}}})
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=mock_resp,
            ) as mock_get:
                client.get_balances()
                args = mock_get.call_args
                assert "/accounts/explicit_999" in args[0][0]
                # Only 1 call (no discovery needed)
                assert mock_get.call_count == 1

    def test_calls_endpoint_without_fields_param(self):
        """D5-C verify: URL has NO ?fields= query (vs get_positions)."""
        with _build_client(account_id="acct_123") as client:
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, {"securitiesAccount": {"currentBalances": {}}}),
            ) as mock_get:
                client.get_balances()
                call_kwargs = mock_get.call_args.kwargs
                # Verify params NOT passed (or empty)
                assert "params" not in call_kwargs or not call_kwargs.get("params")

    def test_account_id_auto_discovery(self):
        """D-α: account_id None default → triggers get_account_id discovery."""
        with _build_client() as client:  # no account_id explicit
            responses = [
                # First call: GET /accounts (discovery)
                _make_resp(200, [{"securitiesAccount": {"accountNumber": "discovered_456"}}]),
                # Second call: GET /accounts/{id} (balances)
                _make_resp(200, {"securitiesAccount": {"currentBalances": {"cashBalance": 100.0}}}),
            ]
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                side_effect=responses,
            ):
                result = client.get_balances()
            assert result["cash"] == 100.0
            assert client._account_id == "discovered_456"  # cached

    def test_missing_currentBalances_returns_zeros(self):
        """D-ζ defensive: missing currentBalances → all 5 values 0.0."""
        with _build_client(account_id="acct_123") as client:
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, {"securitiesAccount": {}}),
            ):
                result = client.get_balances()
            assert all(v == 0.0 for v in result.values())

    def test_missing_individual_fields_default_zero(self):
        """D-ζ: individual missing fields → 0.0 (via .get(key) or 0)."""
        with _build_client(account_id="acct_123") as client:
            partial_body = {
                "securitiesAccount": {
                    "currentBalances": {
                        "cashBalance": 100.0,
                        # buyingPower, liquidationValue, marginBalance, dayTradingBuyingPower missing
                    }
                }
            }
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, partial_body),
            ):
                result = client.get_balances()
            assert result["cash"] == 100.0
            assert result["buying_power"] == 0.0
            assert result["total_value"] == 0.0
            assert result["margin_used"] == 0.0
            assert result["day_trading_buying_power"] == 0.0

    def test_none_value_coalesces_to_zero(self):
        """D-ζ defensive: explicit None values from Schwab response → 0.0."""
        with _build_client(account_id="acct_123") as client:
            none_body = {
                "securitiesAccount": {
                    "currentBalances": {
                        "cashBalance": None,
                        "buyingPower": 50000.0,
                        "liquidationValue": None,
                        "marginBalance": 0,
                        "dayTradingBuyingPower": None,
                    }
                }
            }
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, none_body),
            ):
                result = client.get_balances()
            assert result["cash"] == 0.0  # None → 0
            assert result["buying_power"] == 50000.0
            assert result["total_value"] == 0.0
            assert result["margin_used"] == 0.0  # 0 (falsy) → 0
            assert result["day_trading_buying_power"] == 0.0

    def test_float_conversion_int_input(self):
        """D-ζ: int input → float output."""
        with _build_client(account_id="acct_123") as client:
            int_body = {
                "securitiesAccount": {
                    "currentBalances": {
                        "cashBalance": 50000,  # int
                        "buyingPower": 100000,
                        "liquidationValue": 150000,
                        "marginBalance": 25000,
                        "dayTradingBuyingPower": 200000,
                    }
                }
            }
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, int_body),
            ):
                result = client.get_balances()
            assert all(isinstance(v, float) for v in result.values())

    def test_401_retry_pattern(self):
        """D-ε: 401 first attempt → refresh + retry success."""
        with _build_client(account_id="acct_123") as client:
            responses = [
                _make_resp(401, {"error": "expired"}),
                _make_resp(200, {"securitiesAccount": {"currentBalances": {"cashBalance": 100.0}}}),
            ]
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                side_effect=responses,
            ):
                result = client.get_balances()
            assert result["cash"] == 100.0
            client._refresh_access_token.assert_called_once()

    def test_http_500_raises_api_error(self):
        """Non-200 status (not 401) → SchwabAPIError."""
        with _build_client(account_id="acct_123") as client:
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(500, {"error": "internal"}),
            ):
                with pytest.raises(SchwabAPIError, match="HTTP 500"):
                    client.get_balances()

    def test_httpx_request_error_raises_api_error(self):
        """Network error (httpx.RequestError) → SchwabAPIError."""
        with _build_client(account_id="acct_123") as client:
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                side_effect=httpx.RequestError("network unreachable"),
            ):
                with pytest.raises(SchwabAPIError, match="request failed"):
                    client.get_balances()
