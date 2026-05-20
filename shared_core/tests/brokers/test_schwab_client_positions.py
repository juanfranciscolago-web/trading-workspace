"""Unit tests for SchwabClient.get_account_id + get_positions (S.11.atlas-b).

Covers ADR-013 D2-D5 + sub-decisions D-α (init arg), D-β (port + SchwabAPIError),
D-γ (agnostic asset class), D-δ (signed quantity), D-ε (401 retry pattern).
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
        api_key="test_api_key",
        api_secret="test_api_secret",
        access_token="test_access",
        refresh_token="test_refresh",
    )
    client = SchwabClient(
        credentials,
        paper_trading=True,
        rate_limit_per_second=100,
        account_id=account_id,
    )
    # Patch auth + rate limiter to no-op
    client._refresh_access_token = MagicMock()
    client.rate_limiter.wait_if_needed = MagicMock()
    yield client


# ── TestGetAccountId (4 tests) ─────────────────────────────────────────────────


class TestGetAccountId:
    """D-β: get_account_id port from Eolo + SchwabAPIError contract."""

    def test_success_first_call_caches(self):
        """Discovery via GET /accounts picks first + caches."""
        with _build_client() as client:
            mock_resp = _make_resp(200, [
                {"securitiesAccount": {"accountNumber": "123456789"}},
                {"securitiesAccount": {"accountNumber": "987654321"}},
            ])
            with patch("shared_core.brokers.schwab_client.httpx.get", return_value=mock_resp):
                result = client.get_account_id()
            assert result == "123456789"  # picks first
            assert client._account_id == "123456789"  # cached

    def test_cached_skips_api_call(self):
        """If account_id set en __init__, NO API call (D-α + D9-1)."""
        with _build_client(account_id="explicit_acct_999") as client:
            with patch("shared_core.brokers.schwab_client.httpx.get") as mock_get:
                result = client.get_account_id()
            assert result == "explicit_acct_999"
            mock_get.assert_not_called()  # no API call needed

    def test_empty_accounts_raises_api_error(self):
        """Empty accounts list raises SchwabAPIError (D-β vs Eolo ValueError)."""
        with _build_client() as client:
            mock_resp = _make_resp(200, [])
            with patch("shared_core.brokers.schwab_client.httpx.get", return_value=mock_resp):
                with pytest.raises(SchwabAPIError, match="empty or invalid"):
                    client.get_account_id()

    def test_missing_account_number_raises_api_error(self):
        """Account dict missing accountNumber raises SchwabAPIError."""
        with _build_client() as client:
            mock_resp = _make_resp(200, [{"securitiesAccount": {}}])
            with patch("shared_core.brokers.schwab_client.httpx.get", return_value=mock_resp):
                with pytest.raises(SchwabAPIError, match="missing accountNumber"):
                    client.get_account_id()


# ── TestGetPositions (6 tests) ─────────────────────────────────────────────────


class TestGetPositions:
    """D-γ agnostic + D-δ signed quantity + D-ε 401 retry."""

    def test_returns_normalized_list(self):
        """Basic positions list returned con normalized keys."""
        with _build_client(account_id="acct_123") as client:
            positions_body = {
                "securitiesAccount": {
                    "positions": [
                        {
                            "instrument": {"symbol": "SPY", "assetType": "EQUITY"},
                            "longQuantity": 100,
                            "shortQuantity": 0,
                            "averagePrice": 450.0,
                            "marketValue": 45100.0,
                            "currentDayProfitLoss": 100.0,
                        }
                    ]
                }
            }
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, positions_body),
            ):
                result = client.get_positions()
            assert len(result) == 1
            assert result[0]["symbol"] == "SPY"
            assert result[0]["asset_class"] == "EQUITY"
            assert result[0]["quantity"] == 100  # signed positive
            assert result[0]["market_value"] == 45100.0
            assert result[0]["unrealized_pnl"] == 100.0

    def test_uses_explicit_account_id_no_discovery(self):
        """account_id set en __init__ skips get_account_id discovery (D-α + D9-1)."""
        with _build_client(account_id="explicit_999") as client:
            mock_resp = _make_resp(200, {"securitiesAccount": {"positions": []}})
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=mock_resp,
            ) as mock_get:
                client.get_positions()
                # Verify URL uses explicit account_id (NOT /accounts list for discovery)
                args = mock_get.call_args
                url = args[0][0]  # first positional arg
                assert "/accounts/explicit_999" in url
                # Only 1 call (no discovery call before positions call)
                assert mock_get.call_count == 1

    def test_short_quantity_negative_signed(self):
        """D-δ: shortQuantity → negative signed quantity."""
        with _build_client(account_id="acct_123") as client:
            positions_body = {
                "securitiesAccount": {
                    "positions": [
                        {
                            "instrument": {"symbol": "QQQ", "assetType": "EQUITY"},
                            "longQuantity": 0,
                            "shortQuantity": 50,  # short position
                            "averagePrice": 400.0,
                            "marketValue": -20000.0,
                            "currentDayProfitLoss": 0.0,
                        }
                    ]
                }
            }
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, positions_body),
            ):
                result = client.get_positions()
            assert result[0]["quantity"] == -50  # negative signed

    def test_agnostic_returns_options_and_equities(self):
        """D-γ: NO OPTION-only filter. Returns both asset classes."""
        with _build_client(account_id="acct_123") as client:
            positions_body = {
                "securitiesAccount": {
                    "positions": [
                        {
                            "instrument": {"symbol": "SPY", "assetType": "EQUITY"},
                            "longQuantity": 100, "shortQuantity": 0,
                            "averagePrice": 450.0, "marketValue": 45000.0,
                            "currentDayProfitLoss": 0.0,
                        },
                        {
                            "instrument": {
                                "symbol": "SPY_062626P450",
                                "assetType": "OPTION",
                                "putCall": "PUT",
                                "strikePrice": 450.0,
                                "expirationDate": "2026-06-26",
                            },
                            "longQuantity": 0, "shortQuantity": 5,
                            "averagePrice": 2.5, "marketValue": -1250.0,
                            "currentDayProfitLoss": 50.0,
                        },
                    ]
                }
            }
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, positions_body),
            ):
                result = client.get_positions()
            assert len(result) == 2
            asset_classes = {p["asset_class"] for p in result}
            assert "EQUITY" in asset_classes
            assert "OPTION" in asset_classes
            # OPTION-specific fields populated
            option_pos = next(p for p in result if p["asset_class"] == "OPTION")
            assert option_pos["option_type"] == "PUT"
            assert option_pos["strike"] == 450.0
            assert option_pos["expiration"] == "2026-06-26"
            # EQUITY no OPTION-specific fields
            equity_pos = next(p for p in result if p["asset_class"] == "EQUITY")
            assert "option_type" not in equity_pos

    def test_empty_positions_returns_empty_list(self):
        """No positions → empty list (no error)."""
        with _build_client(account_id="acct_123") as client:
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                return_value=_make_resp(200, {"securitiesAccount": {"positions": []}}),
            ):
                result = client.get_positions()
            assert result == []

    def test_401_retry_pattern(self):
        """D-ε: 401 first attempt → refresh token + retry success."""
        with _build_client(account_id="acct_123") as client:
            responses = [
                _make_resp(401, {"error": "expired"}),
                _make_resp(200, {"securitiesAccount": {"positions": []}}),
            ]
            with patch(
                "shared_core.brokers.schwab_client.httpx.get",
                side_effect=responses,
            ):
                result = client.get_positions()
            assert result == []
            client._refresh_access_token.assert_called_once()
