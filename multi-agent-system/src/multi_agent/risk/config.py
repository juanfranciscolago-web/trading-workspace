"""
ATLAS configuration loader.

Reads limits.yaml and buckets.yaml from the config directory.
The config directory is resolved from the env var ATLAS_CONFIG_DIR,
falling back to <project_root>/config/.

All limits are immutable Pydantic models after loading.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# Walk up from this file: risk/ -> multi_agent/ -> src/ -> multi-agent-system/
_DEFAULT_CONFIG_DIR = Path(__file__).parent.parent.parent.parent / "config"


def _config_dir() -> Path:
    env = os.environ.get("ATLAS_CONFIG_DIR")
    return Path(env) if env else _DEFAULT_CONFIG_DIR


# ── Pydantic models ───────────────────────────────────────────────────────────

class PnlLimits(BaseModel):
    model_config = {"frozen": True}
    daily_halt_pct: float
    weekly_halt_pct: float
    monthly_size_reduction_pct: float
    drawdown_halt_pct: float
    drawdown_kill_switch_pct: float
    daily_loss_kill_switch_pct: float


class ExposureLimits(BaseModel):
    model_config = {"frozen": True}
    single_name_max_pct: float
    sector_max_pct: float
    bucket_max_pct: float
    beta_min: float
    beta_max: float


class GreekLimits(BaseModel):
    model_config = {"frozen": True}
    vega_limit_pct_per_vix_point: float


class BuyingPowerLimits(BaseModel):
    model_config = {"frozen": True}
    normal_max_pct: float
    macro_event_max_pct: float


class Phase1Limits(BaseModel):
    """All ATLAS limits for Phase 1 (paper trading)."""
    model_config = {"frozen": True}
    phase: int
    pnl: PnlLimits
    exposure: ExposureLimits
    greeks: GreekLimits
    buying_power: BuyingPowerLimits


class BucketDef(BaseModel):
    model_config = {"frozen": True}
    description: str
    tickers: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict) -> BucketDef:
        return cls(description=data["description"], tickers=tuple(data.get("tickers", [])))


class BucketConfig(BaseModel):
    """Ticker → bucket membership lookup."""
    model_config = {"frozen": True}
    buckets: dict[str, BucketDef]

    def bucket_for(self, ticker: str) -> str:
        """Return the bucket name for a ticker, or 'other' if not found."""
        upper = ticker.upper()
        for name, bucket in self.buckets.items():
            if upper in bucket.tickers:
                return name
        return "other"

    def tickers_in_bucket(self, bucket_name: str) -> frozenset[str]:
        """Return the set of tickers in a named bucket."""
        bucket = self.buckets.get(bucket_name)
        return frozenset(bucket.tickers) if bucket else frozenset()


# ── Loaders ───────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_limits() -> Phase1Limits:
    path = _config_dir() / "limits.yaml"
    with path.open() as f:
        raw = yaml.safe_load(f)
    return Phase1Limits.model_validate(raw)


@lru_cache(maxsize=1)
def load_buckets() -> BucketConfig:
    path = _config_dir() / "buckets.yaml"
    with path.open() as f:
        raw = yaml.safe_load(f)
    bucket_defs = {
        name: BucketDef.from_dict(data)
        for name, data in raw["buckets"].items()
    }
    return BucketConfig(buckets=bucket_defs)


def reload_config() -> None:
    """Clear caches — useful in tests that override ATLAS_CONFIG_DIR."""
    load_limits.cache_clear()
    load_buckets.cache_clear()
