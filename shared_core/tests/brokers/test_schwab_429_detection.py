"""Tests for 429 throttling detection (Sprint 12 telemetry-b).

ADR-009 §9.4 #5 Q5 + ADR-013 §7 R6 instrumentation 3 ATLAS-relevant
endpoints (get_positions / get_balances / get_options_chain).
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from shared_core.brokers.schwab_client import (
    SchwabAPIError,
    SchwabClient,
    SchwabCredentials,
)


@contextmanager
def _build_client(account_id: str | None = "123456"):
    """Helper: build SchwabClient mock auth + rate_limiter no-op."""
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
    client._refresh_access_token = MagicMock()
    client.rate_limiter.wait_if_needed = MagicMock()
    yield client


def _mock_429_response():
    resp = MagicMock()
    resp.status_code = 429
    resp.text = "rate limit exceeded"
    return resp


class TestSchwab429Detection:
    """429 HTTP throttling logged across 3 ATLAS endpoints (Q5/R6 Phase 1)."""

    def test_get_positions_429_logs_warning(self, caplog):
        """get_positions 429 emits schwab_429_throttled endpoint=positions."""
        with _build_client() as client:
            with patch("httpx.get", return_value=_mock_429_response()):
                with caplog.at_level(logging.WARNING):
                    with pytest.raises(SchwabAPIError):
                        client.get_positions()
        records = [r for r in caplog.records if r.msg == "schwab_429_throttled"]
        assert len(records) >= 1
        assert records[0].endpoint == "positions"
        assert records[0].status_code == 429

    def test_get_balances_429_logs_warning(self, caplog):
        """get_balances 429 emits schwab_429_throttled endpoint=balances."""
        with _build_client() as client:
            with patch("httpx.get", return_value=_mock_429_response()):
                with caplog.at_level(logging.WARNING):
                    with pytest.raises(SchwabAPIError):
                        client.get_balances()
        records = [r for r in caplog.records if r.msg == "schwab_429_throttled"]
        assert len(records) >= 1
        assert records[0].endpoint == "balances"
        assert records[0].status_code == 429

    def test_get_options_chain_429_logs_warning(self, caplog):
        """get_options_chain 429 emits schwab_429_throttled endpoint=chain."""
        with _build_client() as client:
            with patch("httpx.get", return_value=_mock_429_response()):
                with caplog.at_level(logging.WARNING):
                    with pytest.raises(SchwabAPIError):
                        client.get_options_chain("SPY")
        records = [r for r in caplog.records if r.msg == "schwab_429_throttled"]
        assert len(records) >= 1
        assert records[0].endpoint == "chain"
        assert records[0].status_code == 429
