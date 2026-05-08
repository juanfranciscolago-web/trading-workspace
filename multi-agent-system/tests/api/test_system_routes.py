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

from multi_agent.alerts.events import AlertEventType, AlertSeverity
from multi_agent.api.dependencies import get_system_repo
from multi_agent.config import REAL_MODE_TOKEN


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
_P_BUS       = "multi_agent.api.routes.system.check_bus"
_P_ATLAS     = "multi_agent.api.routes.system.check_atlas"
_P_DB        = "multi_agent.api.routes.system.check_db"
_P_ALERT_BUS = "multi_agent.api.routes.system._bus"


def _make_app(initial_mode: str = "paper"):
    from multi_agent.api.app import create_app
    app = create_app()
    app.state.pool = MagicMock()
    app.state.buckets = _make_buckets()
    app.state.limits = _make_limits()
    app.state.startup_time = _STARTUP
    app.state.trading_mode = {
        "mode": initial_mode,
        "since": _STARTUP,
        "source": "env",
    }
    return app


@pytest.fixture
def client():
    with patch(_P_BUS, return_value=("ok", 2.0)), \
         patch(_P_ATLAS, return_value=("ok", 0.5)), \
         patch(_P_DB, return_value=("ok", 10.0)):
        yield TestClient(_make_app())


@pytest.fixture
def post_setup(monkeypatch):
    """Yields (client, app, mock_repo, mock_bus) for POST /system/mode tests."""
    app = _make_app(initial_mode="paper")

    mock_repo = MagicMock()
    app.dependency_overrides[get_system_repo] = lambda: mock_repo

    mock_bus = MagicMock()
    mock_bus.publish.return_value = 1
    monkeypatch.setattr(_P_ALERT_BUS, mock_bus)

    yield TestClient(app), app, mock_repo, mock_bus


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


# ── POST /system/mode ─────────────────────────────────────────────────────────

class TestSystemModePost:

    def test_idempotent_paper_to_paper_no_db_write(self, post_setup):
        client, _, mock_repo, mock_bus = post_setup
        resp = client.post("/system/mode", json={"mode": "paper"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "paper"
        mock_repo.insert_mode_change.assert_not_called()
        mock_bus.publish.assert_not_called()

    def test_paper_to_real_without_token_403(self, post_setup):
        client, _, mock_repo, mock_bus = post_setup
        resp = client.post("/system/mode", json={"mode": "real"})
        assert resp.status_code == 403
        mock_repo.insert_mode_change.assert_not_called()
        mock_bus.publish.assert_not_called()

    def test_paper_to_real_wrong_token_403(self, post_setup):
        client, _, mock_repo, mock_bus = post_setup
        resp = client.post(
            "/system/mode",
            json={"mode": "real", "confirmation_token": "WRONG"},
        )
        assert resp.status_code == 403
        mock_repo.insert_mode_change.assert_not_called()
        mock_bus.publish.assert_not_called()

    def test_paper_to_real_correct_token_200_critical_alert(self, post_setup):
        client, app, mock_repo, mock_bus = post_setup
        new_since = datetime(2026, 5, 8, 19, 0, tzinfo=timezone.utc)
        mock_repo.insert_mode_change.return_value = {
            "mode": "real",
            "changed_at": new_since,
            "source": "api",
        }
        resp = client.post(
            "/system/mode",
            json={"mode": "real", "confirmation_token": REAL_MODE_TOKEN},
        )
        assert resp.status_code == 200
        assert resp.json()["mode"] == "real"
        mock_repo.insert_mode_change.assert_called_once_with(
            mode="real",
            source="api",
            confirmation_token=REAL_MODE_TOKEN,
            actor=None,
        )
        assert mock_bus.publish.call_count == 1
        event = mock_bus.publish.call_args[0][0]
        assert event.severity == AlertSeverity.CRITICAL
        assert app.state.trading_mode["mode"] == "real"
        assert app.state.trading_mode["source"] == "api"

    def test_real_to_paper_without_token_200_warn_alert(self, post_setup):
        client, app, mock_repo, mock_bus = post_setup
        app.state.trading_mode = {
            "mode": "real",
            "since": _STARTUP,
            "source": "api",
        }
        new_since = datetime(2026, 5, 8, 19, 5, tzinfo=timezone.utc)
        mock_repo.insert_mode_change.return_value = {
            "mode": "paper",
            "changed_at": new_since,
            "source": "api",
        }
        resp = client.post("/system/mode", json={"mode": "paper"})
        assert resp.status_code == 200
        assert resp.json()["mode"] == "paper"
        mock_repo.insert_mode_change.assert_called_once_with(
            mode="paper",
            source="api",
            confirmation_token=None,
            actor=None,
        )
        assert mock_bus.publish.call_count == 1
        event = mock_bus.publish.call_args[0][0]
        assert event.severity == AlertSeverity.WARN

    def test_invalid_mode_422(self, post_setup):
        client, _, mock_repo, mock_bus = post_setup
        resp = client.post("/system/mode", json={"mode": "hybrid"})
        assert resp.status_code == 422
        mock_repo.insert_mode_change.assert_not_called()
        mock_bus.publish.assert_not_called()

    def test_emit_alert_with_correct_payload_and_title(self, post_setup):
        client, _, mock_repo, mock_bus = post_setup
        mock_repo.insert_mode_change.return_value = {
            "mode": "real",
            "changed_at": datetime(2026, 5, 8, 19, 0, tzinfo=timezone.utc),
            "source": "api",
        }
        client.post(
            "/system/mode",
            json={"mode": "real", "confirmation_token": REAL_MODE_TOKEN},
        )
        event = mock_bus.publish.call_args[0][0]
        assert event.event_type == AlertEventType.MODE_CHANGED
        assert event.title == "Trading mode changed to REAL"
        assert event.payload == {"from": "paper", "to": "real", "source": "api"}
        assert event.source == "api"
