"""Tests for ATHENA prompt metrics instrumentation (Sprint 12 telemetry-b).

ADR-009 §9.4 #7 Q7 + Sprint 10 F-r6.5 budget reality measurement Phase 1.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock
from uuid import uuid4

from multi_agent.agents.athena_agent import AthenaAgent
from multi_agent.agents.athena_prompt import SYSTEM_PROMPT


def _mock_no_setup_response():
    """LLM response Shape B (no_setup) — minimal valid path no parsing branch."""
    resp = MagicMock()
    resp.text = '{"no_setup": true, "reason": "test telemetry"}'
    resp.request_id = "test-request-id"
    return resp


def _mock_data_layer():
    """data_layer.snapshot().to_dict() returns serializable dict."""
    mock_state = MagicMock()
    mock_state.to_dict.return_value = {"test": "data"}
    mock_state.timestamp = "2026-05-26T00:00:00Z"
    layer = MagicMock()
    layer.snapshot.return_value = mock_state
    layer.data_sources.return_value = ["test"]
    return layer


class TestAthenaPromptMetrics:
    """ATHENA prompt char count instrumented per generate_proposal call.

    ADR-009 §9.4 #7 Q7 + Sprint 10 F-r6.5 budget reality measurement.
    """

    def test_athena_prompt_metrics_logged_on_generate_proposal(self, caplog):
        """generate_proposal emits athena_prompt_metrics event con char counts."""
        mock_router = MagicMock()
        mock_router.send.return_value = _mock_no_setup_response()

        agent = AthenaAgent(claude_router=mock_router, data_layer=_mock_data_layer())

        with caplog.at_level(logging.INFO):
            try:
                agent.generate_proposal(correlation_id=uuid4())
            except Exception:
                pass  # only care about prompt metrics logged pre-send

        records = [r for r in caplog.records if r.msg == "athena_prompt_metrics"]
        assert len(records) >= 1

    def test_athena_prompt_metrics_system_chars_matches_prompt_len(self, caplog):
        """system_chars value matches len(SYSTEM_PROMPT)."""
        mock_router = MagicMock()
        mock_router.send.return_value = _mock_no_setup_response()

        agent = AthenaAgent(claude_router=mock_router, data_layer=_mock_data_layer())

        cid = uuid4()
        with caplog.at_level(logging.INFO):
            try:
                agent.generate_proposal(correlation_id=cid)
            except Exception:
                pass

        records = [r for r in caplog.records if r.msg == "athena_prompt_metrics"]
        assert len(records) >= 1
        record = records[0]
        assert record.system_chars == len(SYSTEM_PROMPT)
        assert record.correlation_id == str(cid)
        assert record.user_chars > 0
        assert record.event == "athena_prompt_metrics"
