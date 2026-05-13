"""Integration test for SchwabDataLayer against real Schwab API (S.5.6f).

⚠️  WARNING — FIRESTORE TOKEN ROTATION ⚠️

These tests instantiate SchwabClient.from_gcp() and may trigger Schwab
OAuth refresh (when the cached access_token is stale), which rotates the
refresh_token in Firestore (collection 'schwab-tokens', document
'schwab-tokens-auth'). This document is shared with Eolo running bots.

If Schwab token rotation happens while Eolo is mid-cycle, Eolo's next
refresh attempt will fail (Schwab invalidates the prior refresh_token on
each successful refresh). Eolo will recover on its next scheduled refresh
via the `refresh_tokens` Cloud Function, but the gap may cause missed
intraday cycles.

DO NOT run these tests while Eolo is actively trading (market hours).
Run during market closed periods only (after 16:00 ET weekdays, or
weekends).

GATING:
- Tests skip unless env var RUN_REAL_SCHWAB_TESTS=1 is set.
- Tests also require GCP credentials (ADC locally, SA JSON in CI).
- Both conditions must be met or pytest skips with clear reason.

USAGE (manual operator invocation only):

    RUN_REAL_SCHWAB_TESTS=1 pytest tests/data_layer/test_schwab_data_layer_integration.py -v

Echoes warning at runtime even when -v is not set.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from multi_agent.data_layer import SchwabDataLayer
from multi_agent.data_layer.interfaces import MarketState
from multi_agent.data_layer.universe import TICKER_UNIVERSE
from shared_core.brokers.schwab_client import SchwabClient

logger = logging.getLogger(__name__)


# ── Gating helper ────────────────────────────────────────────────────────────

def _skip_if_not_real_schwab() -> None:
    """Skip unless explicitly enabled + GCP credentials available.

    Both conditions required:
    1. RUN_REAL_SCHWAB_TESTS=1 in env (operator opt-in).
    2. GCP credentials present (SA JSON via GOOGLE_APPLICATION_CREDENTIALS
       OR ADC default file from `gcloud auth application-default login`).
    """
    if not os.environ.get("RUN_REAL_SCHWAB_TESTS"):
        pytest.skip(
            "Real Schwab integration test gated. Set RUN_REAL_SCHWAB_TESTS=1 "
            "to enable. See module docstring for safety warnings about "
            "Firestore token rotation while Eolo is trading."
        )

    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return  # SA JSON path (CI / prod).

    adc_path = Path.home() / ".config/gcloud/application_default_credentials.json"
    if adc_path.exists():
        return  # ADC user-creds path (dev local).

    pytest.skip(
        "No GCP credentials available. Set GOOGLE_APPLICATION_CREDENTIALS "
        "or run `gcloud auth application-default login`."
    )


# ── Integration test ─────────────────────────────────────────────────────────

class TestSchwabDataLayerIntegration:
    """Real Schwab API integration. Gated by RUN_REAL_SCHWAB_TESTS=1.

    Only structural assertions — D-zzz: no deep data assertions (skew/IV
    values vary by market state, off-hours / holiday windows can return
    empty chains).
    """

    def test_snapshot_returns_valid_market_state(self):
        """Full snapshot end-to-end: from_gcp → SchwabDataLayer → snapshot → MarketState.

        Exercises ALL Sprint 5 Schwab paths in a single test (D-yyy: one
        test, 12 Schwab API calls total — 6 tickers × {price_history,
        options_chain}).
        """
        _skip_if_not_real_schwab()

        # Operator-visible warning at runtime (echoes docstring).
        logger.warning(
            "Running real Schwab integration test — may rotate Firestore "
            "refresh_token. Verify Eolo is NOT actively trading."
        )

        client = SchwabClient.from_gcp()
        layer = SchwabDataLayer(client)

        result = layer.snapshot()

        # Structural assertions.
        assert isinstance(result, MarketState)
        assert set(result.tickers.keys()) == set(TICKER_UNIVERSE.keys())

        # 6 choose 2 = 15 unique pairs.
        expected_pairs = len(TICKER_UNIVERSE) * (len(TICKER_UNIVERSE) - 1) // 2
        assert len(result.correlations) == expected_pairs

        # SPY sanity — most liquid ticker, should always return data.
        spy = result.tickers["SPY"]
        assert spy.last_price > 0, "SPY last_price should be positive"
        assert len(spy.ohlcv_daily) > 0, "SPY should have daily OHLCV data"
        assert spy.realized_vol_30d >= 0, "Realized vol should be non-negative"
