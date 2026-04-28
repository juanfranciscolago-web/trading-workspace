# Claude Router

Centralized model selection and cost optimization for the multi-agent trading system.

## Why This Exists

The trading system has 6 agents (Athena, Apollo, Hermes, Nyx, Vesta, Atlas) generating thousands of LLM calls per day. Without intelligent routing, **every call defaults to the most capable model**, costing 5x more than necessary.

This module is the **single entry point** for all Claude API calls. No agent should call the Anthropic SDK directly.

## What It Does

1. **Routes each task to the right model** (Haiku/Sonnet/Opus) based on `task_type` + `criticality`.
2. **Applies prompt caching** automatically (90% discount on cached reads).
3. **Dispatches async-eligible tasks** to Batch API (50% discount).
4. **Falls back gracefully** if a model fails (Opus → Sonnet → Haiku).
5. **Tracks costs** per call, per agent, per task type for monitoring.
6. **Enforces task budgets** to prevent runaway reasoning.

## Cost Impact

Without this router (all-Opus):
- ~$500/month at typical system volume

With this router (tiered 70/25/5):
- ~$100-130/month with caching
- ~$80-100/month with caching + Batch API

**Typical savings: 75-80%.**

## Architecture

```
Agent (Athena, Apollo, ...) 
        ↓
ClaudeRouter.send(task_type, criticality, ...)
        ↓
1. Lookup routing rule for task_type
2. Apply criticality override if specified
3. Decide caching + batch usage
4. Make API call with retries
5. Fallback if needed
6. Track cost
        ↓
ClaudeResponse (text, cost, metadata)
```

## Quick Start

### 1. Install Dependencies

```bash
pip install anthropic pyyaml
```

For development:
```bash
pip install pytest pytest-mock
```

### 2. Set API Key

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Use the Router

```python
from router import get_router, Criticality

router = get_router("config/routing_rules.yaml")

response = router.send(
    task_type="proposal_generation",
    system_prompt=ATHENA_SYSTEM_PROMPT,
    user_prompt="Analyze MSFT for CSP setup with strike 410, 45 DTE",
    agent="athena",
    criticality=Criticality.STANDARD,
)

print(response.text)
print(f"Cost: ${response.cost.total_usd:.4f}")
print(f"Model used: {response.model_used}")
```

### 4. Monitor Usage

```python
summary = router.get_cost_summary()
print(f"Total calls: {summary['total_calls']}")
print(f"Total cost: ${summary['total_cost_usd']}")
print(f"Distribution: {summary['distribution_pct']}")

# Check if usage matches targets
alerts = router.check_targets()
if alerts['alerts']:
    for alert in alerts['alerts']:
        print(f"⚠️  {alert}")
```

## Configuration

All routing rules live in `config/routing_rules.yaml`. Modify without touching code.

### Adding a new task type

```yaml
rules:
  my_new_task:
    default_model: "claude-sonnet-4-6"
    by_criticality:
      low: "claude-haiku-4-5-20251001"
      standard: "claude-sonnet-4-6"
      high: "claude-opus-4-7"
      critical: "claude-opus-4-7"
    async_eligible: false
    enable_caching: true
    max_tokens: 3000
```

### Changing fallback chain

```yaml
fallback:
  enabled: true
  chain:
    "claude-opus-4-7": "claude-sonnet-4-6"
    "claude-sonnet-4-6": "claude-haiku-4-5-20251001"
    "claude-haiku-4-5-20251001": null  # No fallback from cheapest
  max_retries: 2
```

## Task Types Reference

The system has ~25 task types organized in 3 tiers:

### Haiku Tier (high volume, low complexity)
- `sentiment_classification`
- `entity_extraction`
- `options_activity_tagging`
- `message_routing`
- `schema_validation`
- `ticker_summary`
- `social_keyword_detection`
- `alert_formatting`
- `postmortem_simple`
- `macro_release_extraction`

### Sonnet Tier (workhorse — standard reasoning)
- `proposal_generation`
- `cross_examination`
- `earnings_transcript_analysis`
- `narrative_tracking`
- `macro_regime_analysis`
- `sector_rotation_analysis`
- `stress_test_interpretation`
- `postmortem_complex`
- `daily_report`
- `weekly_report`
- `consensus_simple`
- `atlas_validation_green`

### Opus Tier (critical reasoning)
- `consensus_complex`
- `atlas_validation_alert`
- `postmortem_critical`
- `agent_recalibration`
- `contrarian_flag_analysis`
- `new_strategy_design`
- `human_override_validation`
- `regime_inflection_analysis`

See `config/routing_rules.yaml` for full definitions and modifiers.

## Running Tests

```bash
cd claude_router
pytest tests/ -v
```

Expected: all tests pass with no real API calls (everything is mocked).

## Production Deployment Checklist

Before going live in production:

- [ ] Set `ANTHROPIC_API_KEY` securely (AWS Secrets Manager, not env var in code)
- [ ] Enable structured logging output to your log aggregator (Loki, CloudWatch)
- [ ] Wire `CostTracker` to persist metrics to PostgreSQL or Prometheus
- [ ] Set up alerts on cost thresholds (`monitoring_targets` in config)
- [ ] Implement actual Batch API dispatch (current implementation marks as batch but uses sync)
- [ ] Add rate limiting at the router level if needed
- [ ] Test fallback chain in staging by force-failing Opus
- [ ] Validate config schema on startup (extend `_validate_config()`)
- [ ] Add metrics to dashboard: cost_per_trade, cache_hit_rate, fallback_rate
- [ ] Document task_types in agent code so devs use them consistently

## Known Limitations / TODOs

- **Batch API is marked but not dispatched yet** — current implementation logs intent but uses sync calls. Implementing real batch requires a separate worker that polls for completion. Recommended for Sprint 2 once async-eligible volume justifies it.
- **CostTracker is in-memory** — needs persistence layer for production (PostgreSQL recommended).
- **Singleton is process-local** — if running multiple worker processes, each has its own tracker. For aggregate metrics, persist to shared store.
- **No streaming support yet** — agents that want to stream responses for UX would need a separate `send_stream()` method.

## File Structure

```
claude_router/
├── router.py                    # Main module
├── config/
│   └── routing_rules.yaml       # Routing rules (modify without code changes)
├── tests/
│   └── test_router.py           # Unit tests with mocked client
├── examples/
│   └── usage_example.py         # Example showing typical agent usage
├── requirements.txt
└── README.md                    # This file
```

## Contact / Maintainership

Owner: Trading System Team. 
For changes to routing rules, modify `routing_rules.yaml` and create a PR.
For changes to logic, modify `router.py` and ensure tests pass.
