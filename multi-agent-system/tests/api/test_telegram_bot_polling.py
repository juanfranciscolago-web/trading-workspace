"""
Integration tests for TelegramBot lifespan wiring in FastAPI.

Verifies that the correct PTB async lifecycle is invoked:
  startup:  initialize() → start() → updater.start_polling()
  teardown: updater.stop() → stop() → shutdown()

No real Telegram connection is made — the PTB Application is fully mocked.
Marked @pytest.mark.integration because the test starts the full FastAPI app
(including DB pool init, AlertWorker, etc.) via TestClient.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_mock_tg_app(username: str = "LakeAgents_bot") -> MagicMock:
    """Return a fully mocked PTB Application with all lifecycle coroutines."""
    tg = MagicMock()
    tg.initialize = AsyncMock()
    tg.start = AsyncMock()
    tg.stop = AsyncMock()
    tg.shutdown = AsyncMock()
    tg.bot = MagicMock()
    tg.bot.username = username
    updater = MagicMock()
    updater.start_polling = AsyncMock()
    updater.stop = AsyncMock()
    tg.updater = updater
    return tg


@pytest.mark.integration
class TestTelegramBotLifespan:

    def test_polling_started_on_startup(self):
        """initialize(), start(), and updater.start_polling() are called during lifespan startup."""
        mock_tg = _make_mock_tg_app()

        with patch("multi_agent.telegram_bot.bot.build_application", return_value=mock_tg):
            from multi_agent.api.app import create_app
            app = create_app()
            with TestClient(app):
                mock_tg.initialize.assert_called_once()
                mock_tg.start.assert_called_once()
                mock_tg.updater.start_polling.assert_called_once()

    def test_polling_stopped_on_shutdown(self):
        """updater.stop(), stop(), and shutdown() are called during lifespan teardown."""
        mock_tg = _make_mock_tg_app()

        with patch("multi_agent.telegram_bot.bot.build_application", return_value=mock_tg):
            from multi_agent.api.app import create_app
            app = create_app()
            with TestClient(app):
                pass  # startup runs; exit block triggers teardown
            mock_tg.updater.stop.assert_called_once()
            mock_tg.stop.assert_called_once()
            mock_tg.shutdown.assert_called_once()

    def test_missing_token_does_not_crash_api(self):
        """RuntimeError from build_application (no token) logs a warning but API stays up."""
        with patch(
            "multi_agent.telegram_bot.bot.build_application",
            side_effect=RuntimeError("TELEGRAM_BOT_TOKEN not set"),
        ):
            from multi_agent.api.app import create_app
            app = create_app()
            with TestClient(app) as client:
                # Alert pipeline still works
                resp = client.get("/alerts")
                assert resp.status_code == 200
                # tg_app stored as None
                assert app.state.tg_app is None

    def test_bot_start_failure_does_not_crash_api(self):
        """If initialize() raises (bad token, network error), API starts without bot."""
        mock_tg = _make_mock_tg_app()
        mock_tg.initialize = AsyncMock(side_effect=Exception("Unauthorized"))

        with patch("multi_agent.telegram_bot.bot.build_application", return_value=mock_tg):
            from multi_agent.api.app import create_app
            app = create_app()
            with TestClient(app) as client:
                resp = client.get("/alerts")
                assert resp.status_code == 200
                assert app.state.tg_app is None
