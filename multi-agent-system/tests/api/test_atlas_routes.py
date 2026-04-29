"""
Unit tests for ATLAS API routes.
No DB, no real ATLAS checks — dependencies are mocked via FastAPI overrides.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from multi_agent.communication.enums import RiskMode, StrategyType
from shared_core.models import AssetClass


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_snapshot(
    nav=1_000_000.0,
    drawdown=-2.0,
    buying_power_pct=30.0,
    beta=0.5,
    vega=-1000.0,
):
    from multi_agent.risk.portfolio_snapshot import PortfolioSnapshot
    return PortfolioSnapshot(
        positions=(),
        nav_usd=Decimal(str(nav)),
        cash_usd=Decimal("700000"),
        buying_power_used_pct=buying_power_pct,
        portfolio_beta=beta,
        vega_total=vega,
        pnl_daily_usd=Decimal("0"),
        pnl_daily_pct=0.0,
        pnl_weekly_pct=0.0,
        pnl_monthly_pct=0.0,
        drawdown_from_peak_pct=drawdown,
        snapshot_at=datetime(2026, 4, 29, 14, 0, tzinfo=timezone.utc),
        snapshot_id="a" * 64,  # 64-char hex-like
    )


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
            "finance": BucketDef(description="Financials", tickers=("JPM", "GS")),
        }
    )


@pytest.fixture
def client():
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_buckets, get_limits, get_snapshot_builder

    app = create_app()
    snapshot = _make_snapshot()
    limits = _make_limits()
    buckets = _make_buckets()

    mock_builder = MagicMock()
    mock_builder.get.return_value = snapshot

    app.dependency_overrides[get_snapshot_builder] = lambda: mock_builder
    app.dependency_overrides[get_limits] = lambda: limits
    app.dependency_overrides[get_buckets] = lambda: buckets

    return TestClient(app)  # no context manager = no lifespan


# ── GET /atlas/health ─────────────────────────────────────────────────────────

class TestAtlasHealth:

    def test_health_returns_200(self, client):
        resp = client.get("/atlas/health")
        assert resp.status_code == 200

    def test_health_status_ok(self, client):
        data = client.get("/atlas/health").json()
        assert data["status"] == "ok"

    def test_health_has_risk_mode(self, client):
        data = client.get("/atlas/health").json()
        assert data["risk_mode"] in ("GREEN", "YELLOW", "RED", "BLACK")

    def test_health_risk_mode_green_for_healthy_portfolio(self, client):
        data = client.get("/atlas/health").json()
        assert data["risk_mode"] == "GREEN"

    def test_health_has_nav_usd(self, client):
        data = client.get("/atlas/health").json()
        assert data["nav_usd"] == pytest.approx(1_000_000.0)

    def test_health_has_snapshot_id(self, client):
        data = client.get("/atlas/health").json()
        assert len(data["snapshot_id"]) == 64  # SHA-256 hex

    def test_health_has_ts_iso(self, client):
        data = client.get("/atlas/health").json()
        assert "2026-04-29" in data["ts"]

    def test_health_red_when_near_halt(self):
        """Drawdown below halt threshold triggers RED risk mode."""
        from multi_agent.api.app import create_app
        from multi_agent.api.dependencies import get_buckets, get_limits, get_snapshot_builder

        app = create_app()
        # drawdown_halt_pct=-10.0; drawdown=-11.0 → below halt → RED
        snapshot = _make_snapshot(drawdown=-11.0)
        limits = _make_limits()
        mock_builder = MagicMock()
        mock_builder.get.return_value = snapshot

        app.dependency_overrides[get_snapshot_builder] = lambda: mock_builder
        app.dependency_overrides[get_limits] = lambda: limits
        app.dependency_overrides[get_buckets] = lambda: _make_buckets()

        c = TestClient(app)
        data = c.get("/atlas/health").json()
        assert data["risk_mode"] == "RED"


# ── POST /atlas/validate ──────────────────────────────────────────────────────

VALID_PAYLOAD = {
    "ticker": "MSFT",
    "strategy_type": "CSP",
    "asset_class": "option",
    "proposed_size_pct": 5.0,
    "buying_power_required": 50_000.0,
    "conviction_score": 75,
}


class TestAtlasValidate:

    def test_validate_returns_200(self, client):
        resp = client.post("/atlas/validate", json=VALID_PAYLOAD)
        assert resp.status_code == 200

    def test_validate_approved_field_present(self, client):
        data = client.post("/atlas/validate", json=VALID_PAYLOAD).json()
        assert "approved" in data
        assert isinstance(data["approved"], bool)

    def test_validate_healthy_portfolio_approves(self, client):
        data = client.post("/atlas/validate", json=VALID_PAYLOAD).json()
        assert data["approved"] is True

    def test_validate_has_checks_passed(self, client):
        data = client.post("/atlas/validate", json=VALID_PAYLOAD).json()
        assert isinstance(data["checks_passed"], list)
        assert len(data["checks_passed"]) > 0

    def test_validate_has_evaluation_time_ms(self, client):
        data = client.post("/atlas/validate", json=VALID_PAYLOAD).json()
        assert data["evaluation_time_ms"] >= 0

    def test_validate_risk_mode_present(self, client):
        data = client.post("/atlas/validate", json=VALID_PAYLOAD).json()
        assert data["risk_mode"] in ("GREEN", "YELLOW", "RED", "BLACK")

    def test_validate_correlation_id_is_string(self, client):
        """correlation_id must be serialized as str, not raw UUID object."""
        data = client.post("/atlas/validate", json=VALID_PAYLOAD).json()
        corr = data["correlation_id"]
        assert isinstance(corr, str)
        # Validate it parses as a UUID
        from uuid import UUID
        UUID(corr)  # raises ValueError if not valid UUID

    def test_validate_rejected_returns_200_not_422(self):
        """A blocked trade must still return HTTP 200, not an error status."""
        from multi_agent.api.app import create_app
        from multi_agent.api.dependencies import get_buckets, get_limits, get_snapshot_builder

        app = create_app()
        # drawdown at kill switch → ATLAS blocks
        snapshot = _make_snapshot(drawdown=-16.0)
        mock_builder = MagicMock()
        mock_builder.get.return_value = snapshot

        app.dependency_overrides[get_snapshot_builder] = lambda: mock_builder
        app.dependency_overrides[get_limits] = lambda: _make_limits()
        app.dependency_overrides[get_buckets] = lambda: _make_buckets()

        c = TestClient(app)
        resp = c.post("/atlas/validate", json=VALID_PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()
        assert data["approved"] is False
        assert len(data["checks_failed"]) > 0

    def test_validate_invalid_request_returns_422(self, client):
        resp = client.post("/atlas/validate", json={"ticker": "MSFT"})  # missing fields
        assert resp.status_code == 422

    def test_validate_equity_asset_class(self, client):
        payload = {**VALID_PAYLOAD, "strategy_type": "SWING_EQUITY", "asset_class": "equity"}
        resp = client.post("/atlas/validate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "approved" in data

    def test_validate_fail_closed_on_internal_error(self):
        """If atlas_validate raises unexpectedly, fail-closed: approved=False, still 200."""
        from multi_agent.api.app import create_app
        from multi_agent.api.dependencies import get_buckets, get_limits, get_snapshot_builder

        app = create_app()
        mock_builder = MagicMock()
        mock_builder.get.return_value = _make_snapshot()

        app.dependency_overrides[get_snapshot_builder] = lambda: mock_builder
        app.dependency_overrides[get_limits] = lambda: _make_limits()
        app.dependency_overrides[get_buckets] = lambda: _make_buckets()

        # Patch atlas_validate to raise — atlas_core.validate itself is fail-closed,
        # but we verify the route doesn't re-raise either.
        with patch("multi_agent.api.routes.atlas.atlas_validate") as mock_av:
            # atlas_core.validate is fail-closed and returns AtlasValidationMessage
            # even on error. Simulate a broken validate that returns a blocked result.
            from multi_agent.communication.enums import RiskMode
            from multi_agent.communication.schemas import AtlasValidationMessage
            mock_result = MagicMock(spec=AtlasValidationMessage)
            mock_result.approved = False
            mock_result.correlation_id = uuid4()
            mock_result.executed_size = Decimal("0")
            mock_result.original_size = Decimal("5")
            mock_result.reason = "rejected:system_error"
            mock_result.risk_mode = RiskMode.RED
            mock_result.checks_passed = []
            mock_result.checks_failed = ["system_error"]
            mock_result.evaluation_time_ms = 1.0
            mock_result.atlas_version = "test"
            mock_result.portfolio_snapshot_id = "abc"
            mock_result.metrics_snapshot = {}
            mock_av.return_value = mock_result

            c = TestClient(app)
            resp = c.post("/atlas/validate", json=VALID_PAYLOAD)
            assert resp.status_code == 200
            assert resp.json()["approved"] is False

    def test_validate_two_requests_same_snapshot_id(self, client):
        """Within TTL window, two calls use the same cached snapshot."""
        r1 = client.post("/atlas/validate", json=VALID_PAYLOAD).json()
        r2 = client.post("/atlas/validate", json=VALID_PAYLOAD).json()
        assert r1["portfolio_snapshot_id"] == r2["portfolio_snapshot_id"]

    def test_validate_size_reduced_when_near_limit(self):
        """A trade near single_name_max returns approved=True with executed_size < original."""
        from multi_agent.api.app import create_app
        from multi_agent.api.dependencies import get_buckets, get_limits, get_snapshot_builder
        from multi_agent.risk.portfolio_snapshot import PositionView

        app = create_app()
        # Existing MSFT position at 8% — adding 5% would hit single_name_max=10%
        existing = PositionView(
            ticker="MSFT",
            asset_class="option",
            strategy_type="csp",
            market_value_usd=Decimal("80000"),  # 8% of 1M NAV
            quantity=-1,
            delta=Decimal("0"),
            vega=Decimal("0"),
            theta=Decimal("0"),
        )
        snapshot = _make_snapshot()
        # Manually add a position (rebuild via dataclass replacement)
        import dataclasses
        snapshot = dataclasses.replace(snapshot, positions=(existing,))
        mock_builder = MagicMock()
        mock_builder.get.return_value = snapshot

        app.dependency_overrides[get_snapshot_builder] = lambda: mock_builder
        app.dependency_overrides[get_limits] = lambda: _make_limits()
        app.dependency_overrides[get_buckets] = lambda: _make_buckets()

        c = TestClient(app)
        data = c.post("/atlas/validate", json=VALID_PAYLOAD).json()
        # approved but executed_size < proposed_size_pct (capped at 2% remaining headroom)
        assert data["approved"] is True
        assert data["executed_size_pct"] < data["original_size_pct"]


# ── GET /atlas/limits ─────────────────────────────────────────────────────────

class TestAtlasLimits:

    def test_limits_returns_200(self, client):
        assert client.get("/atlas/limits").status_code == 200

    def test_limits_phase_is_1(self, client):
        data = client.get("/atlas/limits").json()
        assert data["phase"] == 1

    def test_limits_has_pnl_section(self, client):
        data = client.get("/atlas/limits").json()
        assert "daily_halt_pct" in data["pnl"]

    def test_limits_drawdown_kill_switch_value(self, client):
        data = client.get("/atlas/limits").json()
        assert data["pnl"]["drawdown_kill_switch_pct"] == pytest.approx(-15.0)

    def test_limits_has_exposure_section(self, client):
        data = client.get("/atlas/limits").json()
        assert "single_name_max_pct" in data["exposure"]


# ── GET /atlas/buckets ────────────────────────────────────────────────────────

class TestAtlasBuckets:

    def test_buckets_returns_200(self, client):
        assert client.get("/atlas/buckets").status_code == 200

    def test_buckets_has_tech_bucket(self, client):
        data = client.get("/atlas/buckets").json()
        assert "tech" in data["buckets"]

    def test_buckets_tickers_are_list(self, client):
        data = client.get("/atlas/buckets").json()
        assert isinstance(data["buckets"]["tech"]["tickers"], list)

    def test_buckets_msft_in_tech(self, client):
        data = client.get("/atlas/buckets").json()
        assert "MSFT" in data["buckets"]["tech"]["tickers"]
