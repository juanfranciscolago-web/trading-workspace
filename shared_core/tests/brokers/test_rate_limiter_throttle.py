"""Tests for RateLimiter throttle counter + logging (Sprint 12 telemetry-b).

ADR-009 §9.4 #5 Q5 + ADR-013 §7 R6 instrumentation Phase 1.
"""
from __future__ import annotations

import logging
from unittest.mock import patch

from shared_core.brokers.schwab_client import RateLimiter


class TestRateLimiterThrottle:
    """RateLimiter throttle_count counter + log emission verify."""

    def test_throttle_count_starts_zero(self):
        """RateLimiter init throttle_count = 0."""
        rl = RateLimiter(max_calls_per_second=5)
        assert rl.throttle_count == 0

    def test_throttle_count_does_not_increment_under_limit(self):
        """3 calls under max_calls=5 → throttle_count stays 0."""
        rl = RateLimiter(max_calls_per_second=5)
        for _ in range(3):
            rl.wait_if_needed()
        assert rl.throttle_count == 0

    def test_throttle_count_increments_on_sleep(self):
        """5 calls at max_calls=2 → throttle_count >= 1 + time.sleep called."""
        rl = RateLimiter(max_calls_per_second=2)
        with patch("shared_core.brokers.schwab_client.time.sleep") as mock_sleep:
            for _ in range(5):
                rl.wait_if_needed()
        assert rl.throttle_count >= 1
        assert mock_sleep.called

    def test_throttle_logger_warning_emitted_on_sleep(self, caplog):
        """RateLimiter sleep → logger.warning rate_limiter_throttled event con extras."""
        rl = RateLimiter(max_calls_per_second=2)
        with patch("shared_core.brokers.schwab_client.time.sleep"), \
             caplog.at_level(logging.WARNING):
            for _ in range(5):
                rl.wait_if_needed()
        warning_records = [r for r in caplog.records if r.msg == "rate_limiter_throttled"]
        assert len(warning_records) >= 1
        record = warning_records[0]
        assert record.max_calls == 2
        assert record.throttle_count_total >= 1
        assert record.event == "rate_limiter_throttled"
