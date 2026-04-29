"""
Unit tests for AlertDedup.
Redis is mocked — no real Redis needed (integration test for real Redis is e2e).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from multi_agent.alerts.dedup import AlertDedup, make_dedup_key
from multi_agent.alerts.events import AlertEvent, AlertEventType, AlertSeverity


# ── Helpers ───────────────────────────────────────────────────────────────────

def _event(event_type: AlertEventType, payload: dict) -> AlertEvent:
    return AlertEvent(
        event_type=event_type,
        severity=AlertSeverity.WARN,
        title="test",
        payload=payload,
    )


def _mock_redis(set_returns: bool) -> MagicMock:
    """set_returns=True means key was newly set (not a dup)."""
    r = MagicMock()
    r.set.return_value = set_returns
    return r


# ── make_dedup_key tests ──────────────────────────────────────────────────────

class TestMakeDedupKey:

    def test_margin_breach_uses_symbol(self):
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "MSFT"})
        assert make_dedup_key(event) == "alerts:dedup:margin:MSFT"

    def test_stop_loss_uses_position_id(self):
        event = _event(AlertEventType.STOP_LOSS_HIT, {"position_id": "pos-42"})
        assert make_dedup_key(event) == "alerts:dedup:stop:pos-42"

    def test_system_failure_uses_component(self):
        event = _event(AlertEventType.SYSTEM_FAILURE, {"component": "atlas_consumer"})
        assert make_dedup_key(event) == "alerts:dedup:sys:atlas_consumer"

    def test_roll_opportunity_uses_position_and_date(self):
        event = _event(
            AlertEventType.ROLL_OPPORTUNITY,
            {"position_id": "pos-7", "expiry_date": "2026-05-16"},
        )
        assert make_dedup_key(event) == "alerts:dedup:roll:pos-7:2026-05-16"

    def test_missing_payload_field_uses_unknown(self):
        event = _event(AlertEventType.MARGIN_BREACH, {})
        assert make_dedup_key(event) == "alerts:dedup:margin:unknown"


# ── is_duplicate tests ────────────────────────────────────────────────────────

class TestIsDuplicate:

    def test_first_call_is_not_duplicate(self):
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "AAPL"})
        dedup = AlertDedup(redis_client=_mock_redis(set_returns=True))
        is_dup, _ = dedup.is_duplicate(event)
        assert is_dup is False

    def test_second_call_within_window_is_duplicate(self):
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "AAPL"})
        dedup = AlertDedup(redis_client=_mock_redis(set_returns=False))
        is_dup, _ = dedup.is_duplicate(event)
        assert is_dup is True

    def test_stop_loss_uses_long_ttl(self):
        event = _event(AlertEventType.STOP_LOSS_HIT, {"position_id": "pos-1"})
        r = _mock_redis(set_returns=True)
        dedup = AlertDedup(redis_client=r)
        dedup.is_duplicate(event)
        call_kwargs = r.set.call_args[1]
        assert call_kwargs["ex"] == 31_536_000

    def test_margin_breach_ttl_is_1800(self):
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "NVDA"})
        r = _mock_redis(set_returns=True)
        dedup = AlertDedup(redis_client=r)
        dedup.is_duplicate(event)
        assert r.set.call_args[1]["ex"] == 1_800

    def test_system_failure_ttl_is_300(self):
        event = _event(AlertEventType.SYSTEM_FAILURE, {"component": "atlas"})
        r = _mock_redis(set_returns=True)
        dedup = AlertDedup(redis_client=r)
        dedup.is_duplicate(event)
        assert r.set.call_args[1]["ex"] == 300

    def test_roll_opportunity_ttl_is_86400(self):
        event = _event(
            AlertEventType.ROLL_OPPORTUNITY,
            {"position_id": "p1", "expiry_date": "2026-06-20"},
        )
        r = _mock_redis(set_returns=True)
        dedup = AlertDedup(redis_client=r)
        dedup.is_duplicate(event)
        assert r.set.call_args[1]["ex"] == 86_400

    def test_redis_error_fails_open(self):
        """If Redis is unavailable, dedup fails open (not a dup) to avoid silencing alerts."""
        event = _event(AlertEventType.SYSTEM_FAILURE, {"component": "x"})
        r = MagicMock()
        r.set.side_effect = Exception("connection refused")
        dedup = AlertDedup(redis_client=r)
        is_dup, key = dedup.is_duplicate(event)
        assert is_dup is False

    def test_set_called_with_nx_true(self):
        """SET must use NX flag so only the first call within the window wins."""
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "SPY"})
        r = _mock_redis(set_returns=True)
        dedup = AlertDedup(redis_client=r)
        dedup.is_duplicate(event)
        assert r.set.call_args[1]["nx"] is True

    def test_returns_dedup_key_alongside_bool(self):
        event = _event(AlertEventType.MARGIN_BREACH, {"symbol": "QQQ"})
        dedup = AlertDedup(redis_client=_mock_redis(set_returns=True))
        is_dup, key = dedup.is_duplicate(event)
        assert "margin" in key
        assert "QQQ" in key
