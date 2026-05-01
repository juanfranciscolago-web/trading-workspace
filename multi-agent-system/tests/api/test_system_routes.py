"""
Unit tests for /system routes.
No real DB/Redis — check_* functions are patched at the route module level.
app.state set directly (routes read from request.app.state, not Depends).
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_limits():
    from multi_agent.risk.config import (
        BuyingPowerLimits, ExposureLimits, GreekLimits, Phase1Limits, PnlLimits,
    )
    return Phase1Limits(
        phase=1,
        pnl=PnlLimits(
            daily_halt_pct=-3.0,
            weekly_halt_pct=-5.0,
            monthly_size_reduction_pct=-8.0,
            drawdown_halt_pct=-10.0,
            drawdown_kill_switch_pct=-15.0,
            daily_loss_kill_switch_pct=-5.0,
        ),
        exposure=ExposureLimits(
            single_name_max_pct=10.0,
            sector_max_pct=25.0,
            bucket_max_pct=40.0,
            beta_min=-0.5,
            beta_max=2.0,
        ),
        greeks=GreekLimits(vega_limit_pct_per_vix_point=2.0),
        buying_power=BuyingPowerLimits(normal_max_pct=80.0, macro_event_max_pct=50.0),
    )


def _make_buckets():
    from multi_agent.risk.config import BucketConfig, BucketDef
    return BucketConfig(
        buckets={
            "tech": BucketDef(description="Technology", tickers=("MSFT", "AAPL", "NVDA")),
        }
    )


_STARTUP = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
_P_BUS   = "multi_agent.api.routes.system.check_bus"
_P_ATLAS = "multi_agent.api.routes.system.check_atlas"
_P_DB    = "multi_agent.api.routes.system.check_db"


def _make_app():
    from multi_agent.api.app import create_app
    app = create_app()
    app.state.pool = MagicMock()
    app.state.buckets = _make_buckets()
    app.state.limits = _make_limits()
    app.state.startup_time = _STARTUP
    return app


@pytest.fixture
def client():
    with patch(_P_BUS, return_value=("ok", 2.0)), \
         patch(_P_ATLAS, return_value=("ok", 0.5)), \
         patch(_P_DB, return_value=("ok", 10.0)):
        yield TestClient(_make_app())


# ── GET /system/status ────────────────────────────────────────────────────────

class TestSystemStatus:

    def test_status_returns_200_with_all_subsystems(self, client):
        resp = client.get("/system/status")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("api", "bus", "atlas", "db", "checks_duration_ms", "checked_at"):
            assert key in data

    def test_status_api_always_ok(self, client):
        data = client.get("/system/status").json()
        assert data["api"] == "ok"

    def test_status_handles_bus_failure_gracefully(self):
        with patch(_P_BUS, return_value=("error", 50.0)), \
             patch(_P_ATLAS, return_value=("ok", 0.5)), \
             patch(_P_DB, return_value=("ok", 10.0)):
            c = TestClient(_make_app())
            resp = c.get("/system/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bus"] == "error"
        assert data["api"] == "ok"

    def test_status_handles_db_failure_gracefully(self):
        with patch(_P_BUS, return_value=("ok", 2.0)), \
             patch(_P_ATLAS, return_value=("ok", 0.5)), \
             patch(_P_DB, return_value=("error", 100.0)):
            c = TestClient(_make_app())
            resp = c.get("/system/status")
        assert resp.status_code == 200
        assert resp.json()["db"] == "error"

    def test_status_handles_atlas_failure_gracefully(self):
        with patch(_P_BUS, return_value=("ok", 2.0)), \
             patch(_P_ATLAS, return_value=("error", 1.0)), \
             patch(_P_DB, return_value=("ok", 10.0)):
            c = TestClient(_make_app())
            resp = c.get("/system/status")
        assert resp.status_code == 200
        assert resp.json()["atlas"] == "error"

    def test_status_checked_at_is_utc_iso(self, client):
        data = client.get("/system/status").json()
        dt = datetime.fromisoformat(data["checked_at"])
        assert dt.tzinfo is not None


# ── GET /system/mode ──────────────────────────────────────────────────────────

class TestSystemMode:

    def test_mode_returns_paper_by_default(self, client):
        resp = client.get("/system/mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "paper"
        assert "since" in data

    def test_mode_since_is_utc_iso(self, client):
        data = client.get("/system/mode").json()
        dt = datetime.fromisoformat(data["since"])
        assert dt.tzinfo is not None
