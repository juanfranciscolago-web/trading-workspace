from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _make_client():
    from multi_agent.api.app import create_app
    app = create_app()
    return TestClient(app)


# ── Happy paths (read real config files) ──────────────────────────────────────

class TestGetLimits:
    def test_returns_200(self):
        client = _make_client()
        assert client.get("/config/limits").status_code == 200

    def test_has_expected_top_level_keys(self):
        client = _make_client()
        data = client.get("/config/limits").json()
        for key in ("phase", "pnl", "exposure", "greeks", "buying_power", "liquidity"):
            assert key in data, f"Missing top-level key: {key}"

    def test_pnl_section_shape(self):
        client = _make_client()
        pnl = client.get("/config/limits").json()["pnl"]
        for key in ("daily_halt_pct", "weekly_halt_pct", "drawdown_halt_pct"):
            assert key in pnl


class TestGetBuckets:
    def test_returns_200(self):
        client = _make_client()
        assert client.get("/config/buckets").status_code == 200

    def test_has_seven_buckets(self):
        client = _make_client()
        # YAML wraps entries under top-level key "buckets"
        buckets = client.get("/config/buckets").json()["buckets"]
        assert len(buckets) == 7

    def test_each_bucket_has_tickers(self):
        client = _make_client()
        buckets = client.get("/config/buckets").json()["buckets"]
        for name, bucket in buckets.items():
            assert "tickers" in bucket, f"Bucket '{name}' missing 'tickers'"
            assert isinstance(bucket["tickers"], list)


# ── Error paths (mocked filesystem) ───────────────────────────────────────────

class TestErrorHandling:
    def test_returns_404_when_file_missing(self, monkeypatch, tmp_path):
        from multi_agent.api.routes import config as config_module
        monkeypatch.setattr(config_module, "_CONFIG_DIR", tmp_path)

        client = _make_client()
        response = client.get("/config/limits")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_returns_500_when_yaml_invalid(self, monkeypatch, tmp_path):
        from multi_agent.api.routes import config as config_module
        # Unclosed flow sequence — guaranteed YAMLError
        (tmp_path / "limits.yaml").write_text("key: [unclosed\n")
        monkeypatch.setattr(config_module, "_CONFIG_DIR", tmp_path)

        client = _make_client()
        response = client.get("/config/limits")
        assert response.status_code == 500
