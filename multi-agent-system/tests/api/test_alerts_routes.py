"""
Unit tests for alerts API routes.
AlertRepository and AlertBus are mocked via FastAPI dependency overrides.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_client(list_return=None):
    from multi_agent.api.app import create_app
    from multi_agent.api.dependencies import get_alert_repo

    app = create_app()
    mock_repo = MagicMock()
    mock_repo.list_alerts.return_value = list_return or []
    app.dependency_overrides[get_alert_repo] = lambda: mock_repo
    return TestClient(app), mock_repo


class TestListAlerts:

    def test_returns_200(self):
        client, _ = _make_client()
        assert client.get("/alerts").status_code == 200

    def test_returns_items_and_count(self):
        client, _ = _make_client()
        data = client.get("/alerts").json()
        assert "items" in data
        assert "count" in data
        assert data["count"] == 0

    def test_severity_filter_forwarded(self):
        client, repo = _make_client()
        client.get("/alerts?severity=CRITICAL")
        repo.list_alerts.assert_called_once_with(
            limit=50, offset=0, severity="CRITICAL", event_type=None
        )

    def test_pagination_params_forwarded(self):
        client, repo = _make_client()
        client.get("/alerts?limit=10&offset=20")
        repo.list_alerts.assert_called_once_with(
            limit=10, offset=20, severity=None, event_type=None
        )


class TestFireTestAlert:

    def test_returns_202_in_development(self):
        client, _ = _make_client()
        with patch.dict("os.environ", {"ENVIRONMENT": "development"}):
            with patch("multi_agent.api.routes.alerts._bus") as mock_bus:
                mock_bus.publish.return_value = 1
                resp = client.post("/alerts/test")
        assert resp.status_code == 202

    def test_returns_404_outside_development(self):
        client, _ = _make_client()
        with patch.dict("os.environ", {"ENVIRONMENT": "production"}):
            resp = client.post("/alerts/test")
        assert resp.status_code == 404

    def test_returns_422_for_unknown_event_type(self):
        client, _ = _make_client()
        with patch.dict("os.environ", {"ENVIRONMENT": "development"}):
            resp = client.post("/alerts/test?event_type=unknown.type")
        assert resp.status_code == 422
