"""
Claude Router — Centralized model selection and cost optimization for the
multi-agent trading system.

This module is the SINGLE entry point for ALL Claude API calls in the system.
No agent should call the Anthropic SDK directly — they all go through this router.

Responsibilities:
    1. Route each task to the appropriate model (Haiku/Sonnet/Opus) based on
       task_type and criticality.
    2. Apply prompt caching automatically for system prompts and reference
       material (90% cost reduction on cached reads).
    3. Dispatch async-eligible tasks to Batch API (50% discount).
    4. Implement fallback architecture (if Opus fails → Sonnet → Haiku).
    5. Track cost metrics per call for monitoring and unit economics.
    6. Enforce task budgets to prevent runaway reasoning.

Usage:
    router = ClaudeRouter.from_config("config/routing_rules.yaml")

    response = router.send(
        task_type="proposal_generation",
        agent="athena",
        criticality="standard",
        system_prompt=ATHENA_SYSTEM_PROMPT,
        user_prompt="Analyze MSFT for CSP setup",
    )

Author: Trading System Team
Version: 1.0
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from anthropic import Anthropic, APIError, APITimeoutError

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and constants
# =============================================================================

class Criticality(str, Enum):
    """Criticality level of a task — affects model selection."""
    LOW = "low"
    STANDARD = "standard"
    HIGH = "high"
    CRITICAL = "critical"


class ModelTier(str, Enum):
    """Available Claude models in the system."""
    HAIKU = "claude-haiku-4-5-20251001"
    SONNET = "claude-sonnet-4-6"
    OPUS = "claude-opus-4-7"


# Cost per million tokens (input, output) — for monitoring/metrics
MODEL_PRICING: dict[str, tuple[float, float]] = {
    ModelTier.HAIKU.value: (1.0, 5.0),
    ModelTier.SONNET.value: (3.0, 15.0),
    ModelTier.OPUS.value: (5.0, 25.0),
}

# Cache pricing multipliers (relative to base input rate)
CACHE_WRITE_MULTIPLIER_5M = 1.25
CACHE_WRITE_MULTIPLIER_1H = 2.0
CACHE_READ_MULTIPLIER = 0.1  # 90% discount

# Batch API discount
BATCH_DISCOUNT = 0.5  # 50% off both input and output


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class CostBreakdown:
    """Cost breakdown for a single Claude API call."""
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    used_batch_api: bool = False
    total_usd: float = 0.0

    def calculate(self) -> None:
        """Calculate total USD cost based on token usage and pricing."""
        if self.model not in MODEL_PRICING:
            logger.warning(f"Unknown model for pricing: {self.model}")
            return

        input_rate, output_rate = MODEL_PRICING[self.model]
        batch_factor = BATCH_DISCOUNT if self.used_batch_api else 1.0

        # Standard input tokens (not cached)
        regular_input_cost = (self.input_tokens / 1_000_000) * input_rate * batch_factor

        # Cache write cost (1.25x for 5min — assumed default)
        cache_write_cost = (
            (self.cache_creation_tokens / 1_000_000)
            * input_rate
            * CACHE_WRITE_MULTIPLIER_5M
            * batch_factor
        )

        # Cache read cost (0.1x = 90% discount)
        cache_read_cost = (
            (self.cache_read_tokens / 1_000_000)
            * input_rate
            * CACHE_READ_MULTIPLIER
            * batch_factor
        )

        # Output cost
        output_cost = (self.output_tokens / 1_000_000) * output_rate * batch_factor

        self.total_usd = regular_input_cost + cache_write_cost + cache_read_cost + output_cost


@dataclass
class ClaudeResponse:
    """Standardized response from the router, regardless of underlying API call."""
    request_id: str
    model_used: str
    text: str
    cost: CostBreakdown
    latency_ms: float
    used_fallback: bool = False
    fallback_chain: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_response: Any = None  # Keep raw for debugging if needed

    def to_dict(self) -> dict:
        """Serialize for logging/persistence."""
        return {
            "request_id": self.request_id,
            "model_used": self.model_used,
            "text": self.text,
            "input_tokens": self.cost.input_tokens,
            "output_tokens": self.cost.output_tokens,
            "cache_creation_tokens": self.cost.cache_creation_tokens,
            "cache_read_tokens": self.cost.cache_read_tokens,
            "total_usd": self.cost.total_usd,
            "latency_ms": self.latency_ms,
            "used_batch_api": self.cost.used_batch_api,
            "used_fallback": self.used_fallback,
            "fallback_chain": self.fallback_chain,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RoutingDecision:
    """Records the routing decision for auditability."""
    task_type: str
    agent: Optional[str]
    criticality: Criticality
    model_selected: str
    rule_matched: str
    used_caching: bool
    used_batch: bool
    max_tokens: int


# =============================================================================
# Cost tracker (in-memory; in production should write to PostgreSQL/Prometheus)
# =============================================================================

class CostTracker:
    """
    Tracks cumulative costs and call distribution.
    In production, this should persist to a metrics backend.
    """

    def __init__(self):
        self.calls_by_model: dict[str, int] = {
            ModelTier.HAIKU.value: 0,
            ModelTier.SONNET.value: 0,
            ModelTier.OPUS.value: 0,
        }
        self.cost_by_model: dict[str, float] = {
            ModelTier.HAIKU.value: 0.0,
            ModelTier.SONNET.value: 0.0,
            ModelTier.OPUS.value: 0.0,
        }
        self.cost_by_agent: dict[str, float] = {}
        self.cost_by_task_type: dict[str, float] = {}
        self.fallback_count = 0
        self.total_calls = 0
        self.total_cache_reads = 0
        self.total_input_tokens = 0
        self.session_start = datetime.now(timezone.utc)

    def record(
        self,
        response: ClaudeResponse,
        agent: Optional[str],
        task_type: str,
    ) -> None:
        """Record a completed call."""
        self.total_calls += 1
        model = response.model_used

        if model in self.calls_by_model:
            self.calls_by_model[model] += 1
            self.cost_by_model[model] += response.cost.total_usd

        if agent:
            self.cost_by_agent[agent] = self.cost_by_agent.get(agent, 0.0) + response.cost.total_usd

        self.cost_by_task_type[task_type] = (
            self.cost_by_task_type.get(task_type, 0.0) + response.cost.total_usd
        )

        if response.used_fallback:
            self.fallback_count += 1

        self.total_cache_reads += response.cost.cache_read_tokens
        self.total_input_tokens += response.cost.input_tokens + response.cost.cache_read_tokens

    def get_summary(self) -> dict:
        """Get a summary of current usage for dashboard."""
        total_cost = sum(self.cost_by_model.values())
        cache_hit_rate = (
            self.total_cache_reads / self.total_input_tokens
            if self.total_input_tokens > 0
            else 0.0
        )
        fallback_rate = self.fallback_count / self.total_calls if self.total_calls > 0 else 0.0

        # Distribution of calls
        distribution = {}
        if self.total_calls > 0:
            for model, count in self.calls_by_model.items():
                distribution[model] = round(count / self.total_calls * 100, 1)

        return {
            "session_start": self.session_start.isoformat(),
            "total_calls": self.total_calls,
            "total_cost_usd": round(total_cost, 4),
            "cost_by_model": {k: round(v, 4) for k, v in self.cost_by_model.items()},
            "calls_by_model": self.calls_by_model,
            "distribution_pct": distribution,
            "cost_by_agent": {k: round(v, 4) for k, v in self.cost_by_agent.items()},
            "cost_by_task_type": {k: round(v, 4) for k, v in self.cost_by_task_type.items()},
            "cache_hit_rate": round(cache_hit_rate, 3),
            "fallback_rate": round(fallback_rate, 3),
            "fallback_count": self.fallback_count,
        }


# =============================================================================
# Main router class
# =============================================================================

class ClaudeRouter:
    """
    Centralized router for all Claude API calls in the multi-agent system.

    Loads routing rules from YAML config, applies caching/batch automatically,
    handles fallbacks, and tracks costs.
    """

    def __init__(
        self,
        config: dict,
        anthropic_client: Optional[Anthropic] = None,
        cost_tracker: Optional[CostTracker] = None,
    ):
        self.config = config
        self.client = anthropic_client or Anthropic()
        self.cost_tracker = cost_tracker or CostTracker()
        self._validate_config()

    @classmethod
    def from_config(cls, config_path: str | Path) -> ClaudeRouter:
        """Load router from YAML config file."""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Routing config not found: {path}")

        with open(path, "r") as f:
            config = yaml.safe_load(f)

        return cls(config=config)

    def _validate_config(self) -> None:
        """Sanity check on config structure."""
        required_top_keys = ["global", "rules", "fallback"]
        for key in required_top_keys:
            if key not in self.config:
                raise ValueError(f"Missing required config key: {key}")

        if "default_model" not in self.config["global"]:
            raise ValueError("global.default_model is required")

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def send(
        self,
        task_type: str,
        system_prompt: str,
        user_prompt: str,
        agent: Optional[str] = None,
        criticality: str | Criticality = Criticality.STANDARD,
        cache_system_prompt: Optional[bool] = None,
        force_batch: Optional[bool] = None,
        force_model: Optional[str] = None,
        max_tokens_override: Optional[int] = None,
    ) -> ClaudeResponse:
        """
        Send a request to Claude with automatic model selection and optimization.

        Args:
            task_type: Type of task (must match a rule in config or use default)
            system_prompt: System prompt (will be cached if appropriate)
            user_prompt: The actual user message
            agent: Which agent is calling (for cost attribution)
            criticality: low / standard / high / critical
            cache_system_prompt: Override config caching behavior
            force_batch: Override batch eligibility
            force_model: Force a specific model (use sparingly, defeats routing)
            max_tokens_override: Override the task budget

        Returns:
            ClaudeResponse with text, cost breakdown, and metadata
        """
        # Normalize criticality
        if isinstance(criticality, str):
            criticality = Criticality(criticality)

        # Make the routing decision
        decision = self._make_routing_decision(
            task_type=task_type,
            criticality=criticality,
            agent=agent,
            cache_override=cache_system_prompt,
            batch_override=force_batch,
            model_override=force_model,
            max_tokens_override=max_tokens_override,
        )

        if self.config["global"].get("log_decisions", False):
            logger.info(
                f"Routing decision: task={task_type} agent={agent} "
                f"criticality={criticality.value} model={decision.model_selected} "
                f"caching={decision.used_caching} batch={decision.used_batch}"
            )

        # Execute with fallback support
        response = self._execute_with_fallback(
            decision=decision,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        # Track for monitoring
        self.cost_tracker.record(response, agent, task_type)

        return response

    def get_cost_summary(self) -> dict:
        """Get current cost/usage summary for dashboard."""
        return self.cost_tracker.get_summary()

    def check_targets(self) -> dict:
        """
        Check if current usage matches monitoring targets.
        Returns dict with alerts for any deviations.
        """
        summary = self.cost_tracker.get_summary()
        targets = self.config.get("monitoring_targets", {})
        alerts = []

        # Check distribution
        if summary["total_calls"] >= 100:  # Only check after some volume
            haiku_pct = summary["distribution_pct"].get(ModelTier.HAIKU.value, 0)
            opus_pct = summary["distribution_pct"].get(ModelTier.OPUS.value, 0)

            if haiku_pct < targets.get("haiku_pct_target", 70) - 15:
                alerts.append(f"Haiku usage low: {haiku_pct}% vs target {targets.get('haiku_pct_target')}%")

            if opus_pct > targets.get("opus_pct_target", 5) + 5:
                alerts.append(f"Opus usage high: {opus_pct}% vs target {targets.get('opus_pct_target')}%")

        # Check cache hit rate
        if summary["total_calls"] >= 50:
            min_cache = targets.get("cache_hit_rate_min", 0.6)
            if summary["cache_hit_rate"] < min_cache:
                alerts.append(
                    f"Cache hit rate low: {summary['cache_hit_rate']} vs target {min_cache}"
                )

        # Check fallback rate
        max_fallback = targets.get("fallback_rate_max", 0.02)
        if summary["fallback_rate"] > max_fallback:
            alerts.append(
                f"Fallback rate high: {summary['fallback_rate']} vs max {max_fallback}"
            )

        # Check daily cost
        daily_threshold = targets.get("daily_cost_alert_threshold", 50)
        if summary["total_cost_usd"] > daily_threshold:
            alerts.append(
                f"Daily cost exceeded threshold: ${summary['total_cost_usd']} > ${daily_threshold}"
            )

        return {
            "alerts": alerts,
            "summary": summary,
            "targets": targets,
        }

    # -------------------------------------------------------------------------
    # Internal: routing logic
    # -------------------------------------------------------------------------

    def _make_routing_decision(
        self,
        task_type: str,
        criticality: Criticality,
        agent: Optional[str],
        cache_override: Optional[bool],
        batch_override: Optional[bool],
        model_override: Optional[str],
        max_tokens_override: Optional[int],
    ) -> RoutingDecision:
        """Determine which model to use and which optimizations to apply."""

        rules = self.config["rules"]
        rule = rules.get(task_type)

        if rule is None:
            # No specific rule — use global default
            logger.warning(
                f"No routing rule for task_type='{task_type}', using global default"
            )
            model = self.config["global"]["default_model"]
            async_eligible = False
            enable_caching = self.config["global"].get("enable_caching", True)
            max_tokens = 4000
            rule_matched = "global_default"
        else:
            # Check criticality-specific override
            by_crit = rule.get("by_criticality", {})
            model = by_crit.get(criticality.value) or rule.get("default_model")

            async_eligible = rule.get("async_eligible", False)
            enable_caching = rule.get("enable_caching", self.config["global"].get("enable_caching", True))
            max_tokens = rule.get("max_tokens", 4000)
            rule_matched = task_type

        # Apply explicit overrides
        if model_override:
            model = model_override
        if cache_override is not None:
            enable_caching = cache_override
        if max_tokens_override:
            max_tokens = max_tokens_override

        # Batch decision
        global_batch_enabled = self.config["global"].get("enable_batch_api", True)
        if batch_override is not None:
            use_batch = batch_override
        else:
            use_batch = async_eligible and global_batch_enabled

        return RoutingDecision(
            task_type=task_type,
            agent=agent,
            criticality=criticality,
            model_selected=model,
            rule_matched=rule_matched,
            used_caching=enable_caching,
            used_batch=use_batch,
            max_tokens=max_tokens,
        )

    # -------------------------------------------------------------------------
    # Internal: execution with fallback
    # -------------------------------------------------------------------------

    def _execute_with_fallback(
        self,
        decision: RoutingDecision,
        system_prompt: str,
        user_prompt: str,
    ) -> ClaudeResponse:
        """Execute the API call, falling back to lower tier on failure."""

        fallback_config = self.config.get("fallback", {})
        fallback_enabled = fallback_config.get("enabled", True)
        fallback_chain_config = fallback_config.get("chain", {})
        max_retries = fallback_config.get("max_retries", 2)

        current_model = decision.model_selected
        attempted_models: list[str] = []
        used_fallback = False

        while current_model is not None:
            attempted_models.append(current_model)

            try:
                return self._make_api_call(
                    model=current_model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=decision.max_tokens,
                    use_caching=decision.used_caching,
                    use_batch=decision.used_batch,
                    max_retries=max_retries,
                    used_fallback=used_fallback,
                    fallback_chain=attempted_models,
                )
            except (APIError, APITimeoutError) as e:
                logger.error(f"API call failed with model {current_model}: {e}")

                if not fallback_enabled:
                    raise

                # Try fallback
                next_model = fallback_chain_config.get(current_model)
                if next_model is None:
                    logger.error(f"No fallback available from {current_model}")
                    raise

                logger.warning(f"Falling back: {current_model} → {next_model}")
                current_model = next_model
                used_fallback = True

        raise RuntimeError("Exhausted fallback chain without success")

    def _make_api_call(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        use_caching: bool,
        use_batch: bool,
        max_retries: int,
        used_fallback: bool,
        fallback_chain: list[str],
    ) -> ClaudeResponse:
        """Make the actual Anthropic API call."""

        request_id = str(uuid.uuid4())
        start_time = time.time()

        # Build system prompt with caching if enabled
        if use_caching:
            system = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system = system_prompt

        messages = [
            {"role": "user", "content": user_prompt}
        ]

        # NOTE: For Batch API, this would dispatch to messages.batches.create
        # and poll for completion. For simplicity in this initial implementation,
        # we use synchronous calls. Batch implementation can be added in a
        # follow-up iteration when async-eligible task volume justifies it.
        if use_batch:
            logger.debug(
                f"Batch API requested for {model} but using sync call. "
                f"TODO: implement batch dispatch for non-time-sensitive tasks."
            )

        # Make the call with retry logic
        last_exception = None
        for attempt in range(max_retries + 1):
            try:
                response = self.client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                )
                break
            except (APIError, APITimeoutError) as e:
                last_exception = e
                if attempt < max_retries:
                    backoff = 2 ** attempt
                    logger.warning(f"Retry {attempt + 1}/{max_retries} after {backoff}s")
                    time.sleep(backoff)
                else:
                    raise
        else:
            if last_exception:
                raise last_exception

        latency_ms = (time.time() - start_time) * 1000

        # Extract response data
        text = ""
        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        # Build cost breakdown
        usage = response.usage
        cost = CostBreakdown(
            model=model,
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0),
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0),
            used_batch_api=use_batch,
        )
        cost.calculate()

        return ClaudeResponse(
            request_id=request_id,
            model_used=model,
            text=text,
            cost=cost,
            latency_ms=latency_ms,
            used_fallback=used_fallback,
            fallback_chain=fallback_chain if used_fallback else [],
            raw_response=response,
        )


# =============================================================================
# Convenience function for system-wide singleton access
# =============================================================================

_global_router: Optional[ClaudeRouter] = None


def get_router(config_path: str = "config/routing_rules.yaml") -> ClaudeRouter:
    """Get or initialize the global router singleton."""
    global _global_router
    if _global_router is None:
        _global_router = ClaudeRouter.from_config(config_path)
    return _global_router


def reset_router() -> None:
    """Reset the singleton (mainly for testing)."""
    global _global_router
    _global_router = None
