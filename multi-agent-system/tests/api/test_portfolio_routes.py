"""
Unit tests for portfolio API routes.
No DB — snapshot_builder is mocked via FastAPI dependency overrides.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from multi_agent.risk.portfolio_snapshot import PortfolioSnapshot, PositionView


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_snapshot(positions=()):
    return PortfolioSnapshot(
        positions=positions,
        nav_usd=Decimal("1000000"),
        cash_usd=Decimal("700000"),
        buying_power_used_pct=30.0,
        portfolio_beta=0.5,
        vega_total=-1000.0,
        pnl_daily_usd=Decimal("0"),
        pnl_daily_pct=0.0,
        pnl_weekly_pct=0.0,
        pnl_monthly_pct=0.0,
        drawdown_from_peak_pct=-2.0,
        snapshot_at=datetime(2026, 4, 29, 14, 0, tzinfo=timezone.utc),
        snapshot_id="a" * 64,
    )


def _make_position():
    return PositionView(
        ticker="MSFT",
        asset_class="option",
        strategy_type="csp",
        market_value_usd=Decimal("50000"),
        quantity=-1,
        delta=Decimal("-25.5"),
        vega=Decimal("-500"),
        theta=Decimal("150"),
    )


@pytest.fixture
def client():
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_snapshot_builder

    app = create_app()
    mock_builder = MagicMock()
    mock_builder.get.return_value = _make_snapshot()
    app.dependency_overrides[get_snapshot_builder] = lambda: mock_builder
    return TestClient(app)


@pytest.fixture
def client_with_position():
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_snapshot_builder

    app = create_app()
    snapshot = dataclasses.replace(_make_snapshot(), positions=(_make_position(),))
    mock_builder = MagicMock()
    mock_builder.get.return_value = snapshot
    app.dependency_overrides[get_snapshot_builder] = lambda: mock_builder
    return TestClient(app)


# ── GET /portfolio/snapshot ───────────────────────────────────────────────────

class TestPortfolioSnapshot:

    def test_snapshot_returns_200(self, client):
        assert client.get("/portfolio/snapshot").status_code == 200

    def test_snapshot_has_nav_usd(self, client):
        data = client.get("/portfolio/snapshot").json()
        assert data["nav_usd"] == pytest.approx(1_000_000.0)

    def test_snapshot_nav_is_float_not_decimal(self, client):
        data = client.get("/portfolio/snapshot").json()
        assert isinstance(data["nav_usd"], float)

    def test_snapshot_has_position_count(self, client):
        data = client.get("/portfolio/snapshot").json()
        assert "position_count" in data

    def test_snapshot_position_count_zero_for_empty(self, client):
        data = client.get("/portfolio/snapshot").json()
        assert data["position_count"] == 0

    def test_snapshot_position_count_one_with_position(self, client_with_position):
        data = client_with_position.get("/portfolio/snapshot").json()
        assert data["position_count"] == 1


# ── GET /portfolio/positions ──────────────────────────────────────────────────

class TestPortfolioPositions:

    def test_positions_returns_200(self, client):
        assert client.get("/portfolio/positions").status_code == 200

    def test_positions_returns_empty_list(self, client):
        data = client.get("/portfolio/positions").json()
        assert data == []

    def test_positions_has_ticker_field_when_non_empty(self, client_with_position):
        data = client_with_position.get("/portfolio/positions").json()
        assert len(data) == 1
        assert data[0]["ticker"] == "MSFT"

    def test_positions_market_value_is_float(self, client_with_position):
        data = client_with_position.get("/portfolio/positions").json()
        assert isinstance(data[0]["market_value_usd"], float)
        assert data[0]["market_value_usd"] == pytest.approx(50_000.0)
