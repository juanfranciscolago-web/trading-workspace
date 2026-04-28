"""
Unit tests for ClaudeRouter.

Tests routing logic, cost calculation, fallback behavior, and config loading.
Uses mocks for the Anthropic client to avoid real API calls.

Run with: pytest tests/test_router.py -v
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from router import (
    ClaudeResponse,
    ClaudeRouter,
    CostBreakdown,
    CostTracker,
    Criticality,
    ModelTier,
    RoutingDecision,
    get_router,
    reset_router,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_config():
    """Minimal config for testing."""
    return {
        "global": {
            "default_model": "claude-sonnet-4-6",
            "enable_caching": True,
            "cache_ttl": "5m",
            "enable_batch_api": True,
            "log_decisions": False,
            "emit_cost_metrics": False,
        },
        "rules": {
            "sentiment_classification": {
                "default_model": "claude-haiku-4-5-20251001",
                "async_eligible": True,
                "enable_caching": True,
                "max_tokens": 500,
            },
            "proposal_generation": {
                "default_model": "claude-sonnet-4-6",
                "by_criticality": {
                    "low": "claude-haiku-4-5-20251001",
                    "standard": "claude-sonnet-4-6",
                    "high": "claude-sonnet-4-6",
                    "critical": "claude-opus-4-7",
                },
                "async_eligible": False,
                "enable_caching": True,
                "max_tokens": 4000,
            },
            "consensus_complex": {
                "default_model": "claude-opus-4-7",
                "async_eligible": False,
                "enable_caching": True,
                "max_tokens": 6000,
            },
            "postmortem_complex": {
                "default_model": "claude-sonnet-4-6",
                "async_eligible": True,
                "enable_caching": True,
                "max_tokens": 3000,
            },
        },
        "fallback": {
            "enabled": True,
            "chain": {
                "claude-opus-4-7": "claude-sonnet-4-6",
                "claude-sonnet-4-6": "claude-haiku-4-5-20251001",
                "claude-haiku-4-5-20251001": None,
            },
            "max_retries": 2,
            "timeout_seconds": 30,
            "flag_for_review": True,
        },
        "monitoring_targets": {
            "haiku_pct_target": 70,
            "sonnet_pct_target": 25,
            "opus_pct_target": 5,
            "cache_hit_rate_min": 0.6,
            "fallback_rate_max": 0.02,
            "cost_per_trade_max": 0.50,
            "daily_cost_alert_threshold": 50,
        },
    }


@pytest.fixture
def mock_client():
    """Mocked Anthropic client."""
    client = MagicMock()

    # Mock a typical response
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Test response text")]
    mock_response.usage = MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    client.messages.create.return_value = mock_response

    return client


@pytest.fixture
def router(sample_config, mock_client):
    """ClaudeRouter with mocked client."""
    return ClaudeRouter(config=sample_config, anthropic_client=mock_client)


# =============================================================================
# Tests: Routing Decision Logic
# =============================================================================

class TestRoutingDecisions:
    """Tests for the routing decision logic."""

    def test_sentiment_classification_routes_to_haiku(self, router):
        """Sentiment classification should always go to Haiku."""
        decision = router._make_routing_decision(
            task_type="sentiment_classification",
            criticality=Criticality.STANDARD,
            agent="nyx",
            cache_override=None,
            batch_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        assert decision.model_selected == ModelTier.HAIKU.value
        assert decision.used_caching is True
        assert decision.used_batch is True  # async_eligible=True + global batch enabled

    def test_proposal_standard_criticality_routes_to_sonnet(self, router):
        """Proposal generation at standard criticality goes to Sonnet."""
        decision = router._make_routing_decision(
            task_type="proposal_generation",
            criticality=Criticality.STANDARD,
            agent="athena",
            cache_override=None,
            batch_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        assert decision.model_selected == ModelTier.SONNET.value

    def test_proposal_critical_criticality_escalates_to_opus(self, router):
        """Critical proposals (high-conviction) escalate to Opus."""
        decision = router._make_routing_decision(
            task_type="proposal_generation",
            criticality=Criticality.CRITICAL,
            agent="apollo",
            cache_override=None,
            batch_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        assert decision.model_selected == ModelTier.OPUS.value

    def test_proposal_low_criticality_downgrades_to_haiku(self, router):
        """Low criticality proposals can use Haiku."""
        decision = router._make_routing_decision(
            task_type="proposal_generation",
            criticality=Criticality.LOW,
            agent="hermes",
            cache_override=None,
            batch_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        assert decision.model_selected == ModelTier.HAIKU.value

    def test_consensus_complex_uses_opus(self, router):
        """Complex consensus decisions always use Opus."""
        decision = router._make_routing_decision(
            task_type="consensus_complex",
            criticality=Criticality.STANDARD,
            agent=None,
            cache_override=None,
            batch_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        assert decision.model_selected == ModelTier.OPUS.value

    def test_unknown_task_type_uses_default(self, router):
        """Unknown task_type falls back to global default."""
        decision = router._make_routing_decision(
            task_type="completely_unknown_task",
            criticality=Criticality.STANDARD,
            agent=None,
            cache_override=None,
            batch_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        assert decision.model_selected == ModelTier.SONNET.value
        assert decision.rule_matched == "global_default"

    def test_model_override_works(self, router):
        """Explicit model_override bypasses routing."""
        decision = router._make_routing_decision(
            task_type="sentiment_classification",
            criticality=Criticality.STANDARD,
            agent=None,
            cache_override=None,
            batch_override=None,
            model_override=ModelTier.OPUS.value,
            max_tokens_override=None,
        )
        assert decision.model_selected == ModelTier.OPUS.value

    def test_async_eligible_task_uses_batch(self, router):
        """Postmortem complex is async_eligible → uses batch."""
        decision = router._make_routing_decision(
            task_type="postmortem_complex",
            criticality=Criticality.STANDARD,
            agent="atlas",
            cache_override=None,
            batch_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        assert decision.used_batch is True

    def test_non_async_task_does_not_use_batch(self, router):
        """Proposal generation is NOT async_eligible → no batch."""
        decision = router._make_routing_decision(
            task_type="proposal_generation",
            criticality=Criticality.STANDARD,
            agent="athena",
            cache_override=None,
            batch_override=None,
            model_override=None,
            max_tokens_override=None,
        )
        assert decision.used_batch is False


# =============================================================================
# Tests: Cost Calculation
# =============================================================================

class TestCostCalculation:
    """Tests for cost calculation logic."""

    def test_haiku_basic_cost(self):
        """Haiku basic call: 1M input + 1M output should be $1 + $5 = $6."""
        cost = CostBreakdown(
            model=ModelTier.HAIKU.value,
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        cost.calculate()
        assert cost.total_usd == pytest.approx(6.0, rel=1e-3)

    def test_sonnet_basic_cost(self):
        """Sonnet basic call: 1M input + 1M output should be $3 + $15 = $18."""
        cost = CostBreakdown(
            model=ModelTier.SONNET.value,
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        cost.calculate()
        assert cost.total_usd == pytest.approx(18.0, rel=1e-3)

    def test_opus_basic_cost(self):
        """Opus basic call: 1M input + 1M output should be $5 + $25 = $30."""
        cost = CostBreakdown(
            model=ModelTier.OPUS.value,
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        cost.calculate()
        assert cost.total_usd == pytest.approx(30.0, rel=1e-3)

    def test_cache_read_discount(self):
        """Cache reads should cost 10% of input rate."""
        # 1M cache reads at Sonnet ($3 base) = $0.30
        cost = CostBreakdown(
            model=ModelTier.SONNET.value,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=1_000_000,
        )
        cost.calculate()
        assert cost.total_usd == pytest.approx(0.30, rel=1e-2)

    def test_cache_write_premium(self):
        """Cache writes should cost 1.25x input rate (5min default)."""
        # 1M cache write at Sonnet ($3 base) * 1.25 = $3.75
        cost = CostBreakdown(
            model=ModelTier.SONNET.value,
            input_tokens=0,
            output_tokens=0,
            cache_creation_tokens=1_000_000,
        )
        cost.calculate()
        assert cost.total_usd == pytest.approx(3.75, rel=1e-2)

    def test_batch_discount(self):
        """Batch API should give 50% off."""
        # Sonnet 1M+1M with batch: $18 * 0.5 = $9
        cost = CostBreakdown(
            model=ModelTier.SONNET.value,
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            used_batch_api=True,
        )
        cost.calculate()
        assert cost.total_usd == pytest.approx(9.0, rel=1e-3)

    def test_cost_savings_vs_all_opus(self):
        """
        Verify the strategic claim: tiered routing saves ~50% vs all-Opus.

        Scenario: 100 calls, each 5K input + 1K output.
        - All Opus: 100 * (5K * $5/M + 1K * $25/M) = 100 * ($0.025 + $0.025) = $5.00
        - Tiered (70/25/5):
            - 70 Haiku: 70 * (5K * $1/M + 1K * $5/M) = 70 * ($0.005 + $0.005) = $0.70
            - 25 Sonnet: 25 * (5K * $3/M + 1K * $15/M) = 25 * ($0.015 + $0.015) = $0.75
            - 5 Opus: 5 * ($0.025 + $0.025) = $0.25
            - Total: $1.70
        Savings: 1 - 1.70/5.00 = 66%
        """
        # All Opus
        all_opus_cost = 0
        for _ in range(100):
            c = CostBreakdown(model=ModelTier.OPUS.value, input_tokens=5000, output_tokens=1000)
            c.calculate()
            all_opus_cost += c.total_usd

        # Tiered
        tiered_cost = 0
        for _ in range(70):
            c = CostBreakdown(model=ModelTier.HAIKU.value, input_tokens=5000, output_tokens=1000)
            c.calculate()
            tiered_cost += c.total_usd
        for _ in range(25):
            c = CostBreakdown(model=ModelTier.SONNET.value, input_tokens=5000, output_tokens=1000)
            c.calculate()
            tiered_cost += c.total_usd
        for _ in range(5):
            c = CostBreakdown(model=ModelTier.OPUS.value, input_tokens=5000, output_tokens=1000)
            c.calculate()
            tiered_cost += c.total_usd

        savings_pct = 1 - (tiered_cost / all_opus_cost)
        assert savings_pct > 0.5  # At least 50% savings (real value ~66%)


# =============================================================================
# Tests: End-to-End Send
# =============================================================================

class TestSend:
    """Tests for the public send() method."""

    def test_send_returns_response(self, router, mock_client):
        """send() returns a ClaudeResponse."""
        response = router.send(
            task_type="sentiment_classification",
            system_prompt="You are a sentiment classifier",
            user_prompt="Tesla beats earnings expectations",
            agent="nyx",
            criticality="standard",
        )
        assert isinstance(response, ClaudeResponse)
        assert response.text == "Test response text"
        assert response.cost.total_usd > 0

    def test_send_uses_correct_model(self, router, mock_client):
        """send() calls the API with the correctly routed model."""
        router.send(
            task_type="consensus_complex",
            system_prompt="You decide consensus",
            user_prompt="Resolve this debate",
            agent=None,
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == ModelTier.OPUS.value

    def test_send_applies_caching(self, router, mock_client):
        """send() with caching enabled wraps system prompt with cache_control."""
        router.send(
            task_type="proposal_generation",
            system_prompt="You are Athena",
            user_prompt="Analyze MSFT",
            agent="athena",
        )
        call_kwargs = mock_client.messages.create.call_args.kwargs
        system = call_kwargs["system"]
        # Caching enabled → system is a list with cache_control
        assert isinstance(system, list)
        assert system[0]["cache_control"]["type"] == "ephemeral"

    def test_send_tracks_cost(self, router, mock_client):
        """send() updates the cost tracker."""
        initial_calls = router.cost_tracker.total_calls
        router.send(
            task_type="sentiment_classification",
            system_prompt="Sentiment classifier",
            user_prompt="News headline",
            agent="nyx",
        )
        assert router.cost_tracker.total_calls == initial_calls + 1


# =============================================================================
# Tests: Fallback Behavior
# =============================================================================

class TestFallback:
    """Tests for fallback architecture."""

    def test_opus_failure_falls_back_to_sonnet(self, sample_config):
        """If Opus fails, router falls back to Sonnet."""
        from anthropic import APIError

        client = MagicMock()

        # First call (Opus) fails, second call (Sonnet) succeeds
        mock_success = MagicMock()
        mock_success.content = [MagicMock(text="Sonnet response")]
        mock_success.usage = MagicMock(
            input_tokens=100, output_tokens=50,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        )

        # Create a proper APIError
        api_error = APIError(
            message="Server error",
            request=MagicMock(),
            body={"error": "internal"},
        )

        client.messages.create.side_effect = [
            api_error, api_error, api_error,  # Opus retries fail
            mock_success,                      # Sonnet succeeds
        ]

        router = ClaudeRouter(config=sample_config, anthropic_client=client)
        response = router.send(
            task_type="consensus_complex",
            system_prompt="You decide",
            user_prompt="Test",
        )

        assert response.used_fallback is True
        assert response.model_used == ModelTier.SONNET.value
        assert ModelTier.OPUS.value in response.fallback_chain


# =============================================================================
# Tests: Cost Tracker
# =============================================================================

class TestCostTracker:
    """Tests for the CostTracker."""

    def test_tracker_records_calls(self):
        """Tracker correctly records calls and costs."""
        tracker = CostTracker()
        cost = CostBreakdown(
            model=ModelTier.SONNET.value,
            input_tokens=1000,
            output_tokens=500,
        )
        cost.calculate()

        response = ClaudeResponse(
            request_id="test",
            model_used=ModelTier.SONNET.value,
            text="text",
            cost=cost,
            latency_ms=100,
        )

        tracker.record(response, agent="athena", task_type="proposal_generation")

        assert tracker.total_calls == 1
        assert tracker.calls_by_model[ModelTier.SONNET.value] == 1
        assert tracker.cost_by_agent["athena"] > 0

    def test_summary_includes_distribution(self):
        """Summary shows correct distribution percentages."""
        tracker = CostTracker()

        # 7 Haiku, 2 Sonnet, 1 Opus = 70/20/10
        for _ in range(7):
            cost = CostBreakdown(model=ModelTier.HAIKU.value, input_tokens=100, output_tokens=50)
            cost.calculate()
            response = ClaudeResponse(
                request_id="test", model_used=ModelTier.HAIKU.value,
                text="t", cost=cost, latency_ms=10,
            )
            tracker.record(response, agent="nyx", task_type="sentiment_classification")

        for _ in range(2):
            cost = CostBreakdown(model=ModelTier.SONNET.value, input_tokens=100, output_tokens=50)
            cost.calculate()
            response = ClaudeResponse(
                request_id="test", model_used=ModelTier.SONNET.value,
                text="t", cost=cost, latency_ms=10,
            )
            tracker.record(response, agent="athena", task_type="proposal_generation")

        cost = CostBreakdown(model=ModelTier.OPUS.value, input_tokens=100, output_tokens=50)
        cost.calculate()
        response = ClaudeResponse(
            request_id="test", model_used=ModelTier.OPUS.value,
            text="t", cost=cost, latency_ms=10,
        )
        tracker.record(response, agent=None, task_type="consensus_complex")

        summary = tracker.get_summary()
        assert summary["total_calls"] == 10
        assert summary["distribution_pct"][ModelTier.HAIKU.value] == 70.0
        assert summary["distribution_pct"][ModelTier.SONNET.value] == 20.0
        assert summary["distribution_pct"][ModelTier.OPUS.value] == 10.0


# =============================================================================
# Tests: Config Loading
# =============================================================================

class TestConfigLoading:
    """Tests for config loading and validation."""

    def test_load_config_from_yaml(self, tmp_path):
        """Router loads correctly from a YAML file."""
        config_content = """
global:
  default_model: "claude-sonnet-4-6"
  enable_caching: true
  enable_batch_api: true

rules:
  test_task:
    default_model: "claude-haiku-4-5-20251001"
    async_eligible: false
    enable_caching: true
    max_tokens: 1000

fallback:
  enabled: true
  chain:
    "claude-sonnet-4-6": "claude-haiku-4-5-20251001"
  max_retries: 1
"""
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(config_content)

        with patch("router.Anthropic"):
            router = ClaudeRouter.from_config(config_path)

        assert router.config["global"]["default_model"] == ModelTier.SONNET.value
        assert "test_task" in router.config["rules"]

    def test_invalid_config_raises(self, tmp_path):
        """Invalid config (missing required keys) raises an error."""
        config_path = tmp_path / "bad_config.yaml"
        config_path.write_text("global:\n  enable_caching: true\n")

        with patch("router.Anthropic"):
            with pytest.raises(ValueError, match="Missing required config key"):
                ClaudeRouter.from_config(config_path)

    def test_missing_config_file_raises(self):
        """Missing config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            ClaudeRouter.from_config("/nonexistent/path.yaml")


# =============================================================================
# Tests: Singleton
# =============================================================================

class TestSingleton:
    """Tests for the singleton accessor."""

    def teardown_method(self):
        """Reset singleton after each test."""
        reset_router()

    def test_get_router_returns_same_instance(self, tmp_path):
        """get_router returns the same instance on multiple calls."""
        config_content = """
global:
  default_model: "claude-sonnet-4-6"
  enable_caching: true
rules: {}
fallback:
  enabled: true
  chain: {}
"""
        config_path = tmp_path / "config.yaml"
        config_path.write_text(config_content)

        with patch("router.Anthropic"):
            r1 = get_router(str(config_path))
            r2 = get_router(str(config_path))
        assert r1 is r2


# =============================================================================
# Tests: Monitoring Targets
# =============================================================================

class TestMonitoring:
    """Tests for monitoring and alerting."""

    def test_check_targets_alerts_on_high_opus_usage(self, router):
        """check_targets() generates alert if Opus usage exceeds target."""
        # Simulate 100 calls all going to Opus (way over 5% target)
        for _ in range(100):
            cost = CostBreakdown(
                model=ModelTier.OPUS.value, input_tokens=100, output_tokens=50,
            )
            cost.calculate()
            response = ClaudeResponse(
                request_id="test", model_used=ModelTier.OPUS.value,
                text="t", cost=cost, latency_ms=10,
            )
            router.cost_tracker.record(response, agent=None, task_type="consensus_complex")

        result = router.check_targets()
        # Multiple alerts may fire; verify Opus alert is in there
        opus_alerts = [a for a in result["alerts"] if "Opus" in a]
        assert len(opus_alerts) > 0, f"No Opus alert in: {result['alerts']}"
