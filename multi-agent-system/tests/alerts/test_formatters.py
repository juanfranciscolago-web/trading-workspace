"""
Unit tests for alert message formatters.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity
from multi_agent.alerts.formatters import format_alert


def _event(event_type: AlertEventType, payload: dict, severity=AlertSeverity.WARN) -> AlertEvent:
    return AlertEvent(
        event_type=event_type,
        severity=severity,
        title="Test Alert",
        payload=payload,
        created_at=datetime(2026, 4, 29, 17, 0, tzinfo=timezone.utc),
    )


class TestEmojiAndHeader:

    def test_critical_uses_siren_emoji(self):
        event = _event(AlertEventType.SYSTEM_FAILURE, {"component": "x"}, AlertSeverity.CRITICAL)
        text = format_alert(event)
        assert "🚨" in text

    def test_warn_uses_arrows_emoji(self):
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "MSFT"}, AlertSeverity.WARN)
        text = format_alert(event)
        assert "🔄" in text

    def test_info_uses_info_emoji(self):
        event = _event(AlertEventType.ROLL_OPPORTUNITY, {"position_id": "p1", "expiry_date": "2026-05-16"}, AlertSeverity.INFO)
        text = format_alert(event)
        assert "ℹ️" in text

    def test_title_in_header(self):
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "AAPL"})
        text = format_alert(event)
        assert "Test Alert" in text


class TestTimestamp:

    def test_timestamp_in_art(self):
        # 2026-04-29 17:00 UTC = 2026-04-29 14:00 ART (UTC-3)
        event = _event(AlertEventType.SYSTEM_FAILURE, {"component": "x"})
        text = format_alert(event)
        assert "14:00:00 ART" in text

    def test_timestamp_line_present(self):
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "SPY"})
        text = format_alert(event)
        assert "ART" in text


class TestBodyFields:

    def test_margin_breach_has_symbol_bold(self):
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "NVDA", "exposure_pct": 12.5, "limit_pct": 10.0})
        text = format_alert(event)
        assert "NVDA" in text
        assert "12.5" in text
        assert "10.0" in text

    def test_stop_loss_has_ticker_and_pnl(self):
        event = _event(AlertEventType.STOP_LOSS_HIT, {"ticker": "MSFT", "pnl_pct": -8.5, "position_id": "pos-42"})
        text = format_alert(event)
        assert "MSFT" in text
        assert "-8.5" in text

    def test_system_failure_has_component_and_error(self):
        event = _event(AlertEventType.SYSTEM_FAILURE, {"component": "atlas_consumer", "error_msg": "timeout"})
        text = format_alert(event)
        # underscores are escaped for MarkdownV1: atlas_consumer → atlas\_consumer
        assert r"atlas\_consumer" in text
        assert "timeout" in text

    def test_roll_opportunity_has_expiry_and_dte(self):
        event = _event(
            AlertEventType.ROLL_OPPORTUNITY,
            {"ticker": "NVDA", "expiry_date": "2026-05-16", "dte": 17, "current_iv": 45.3, "position_id": "p1"},
        )
        text = format_alert(event)
        assert "2026-05-16" in text
        assert "17" in text
        assert "45.3" in text
