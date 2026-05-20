"""
Central configuration — single source of truth for all environment variables.

HIGH priority validators run inside Settings() and raise ValidationError
immediately (fail-fast before any service is initialized).

WARNING priority checks run via log_startup_warnings(), called explicitly
from the FastAPI lifespan after uvicorn has configured logging.

Loading priority (highest → lowest):
  1. Env vars already exported in the shell
  2. .env at workspace root (loaded via python-dotenv, override=False)
  3. Hardcoded defaults below
"""
from __future__ import annotations

import logging
import re
from enum import Enum
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env from workspace root before Settings is instantiated.
# override=False: shell-exported vars always win over .env values.
# Resolves by __file__ so it works regardless of the process CWD.
_WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(_WORKSPACE_ROOT / ".env", override=False)
except ImportError:
    pass  # python-dotenv is a declared dependency; guard is defensive only

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"^\d{8,12}:[A-Za-z0-9_-]{35,}$")
_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class TradingMode(str, Enum):
    PAPER = "paper"
    REAL = "real"


REAL_MODE_TOKEN = "CAUTION_GOING_LIVE_STOPPING_PAPER_GOING_REAL_TRADING"
REAL_MODE_HUMAN_MESSAGE = (
    "CAUTION: YOU ARE GOING LIVE! This action stops Paper and goes REAL TRADING"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",  # silently ignore env vars not declared here
    )

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://trader:trader@localhost:5432/trading"
    DB_POOL_MIN: int = 2
    DB_POOL_MAX: int = 10

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Telegram ──────────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ALLOWED_CHAT_IDS: str = ""  # raw CSV; use .telegram_chat_ids property

    # ── Runtime ───────────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # ── Alerts retry queue ────────────────────────────────────────────────────
    ALERT_RETRY_INTERVAL_SECONDS: int = 30  # poll interval for RetryWorker

    # ── Trading mode ──────────────────────────────────────────────────────────
    TRADING_MODE: TradingMode = TradingMode.PAPER
    TRADING_MODE_CONFIRM: str | None = None

    # ── Schwab integration (Sprint 5+) ────────────────────────────────────────
    # USE_SCHWAB_DATA_LAYER toggles the data source consumed by ATHENA and other
    # real agents:
    #   False (default) → StubDataLayer (synthetic seeded OHLCV/IV/skew).
    #   True            → SchwabDataLayer via SchwabClient.from_gcp() (real
    #                     Schwab broker data). Requires GCP credentials (ADC
    #                     locally, GOOGLE_APPLICATION_CREDENTIALS in CI/prod)
    #                     and the schwab-tokens Firestore doc bootstrapped via
    #                     safe_init_auth_v2.py.
    USE_SCHWAB_DATA_LAYER: bool = False

    # ADR-013 D10: ATLAS live portfolio integration flag (Sprint 11 atlas-d).
    # False (default) = DB-backed SnapshotBuilder (synthetic). True =
    # LiveSnapshotBuilder reads via SchwabClient.get_positions + get_balances.
    # Independent from USE_SCHWAB_DATA_LAYER (ATHENA market data vs ATLAS
    # portfolio reads decoupled).
    USE_LIVE_PORTFOLIO: bool = False

    # ADR-013 D9-1: Explicit Schwab account_id for multi-agent subaccount
    # isolation (Sprint 11 atlas-d). Empty string default = SchwabClient
    # auto-discovery picks first account (Eolo behavior preserved). Set
    # explicit = multi-agent uses specified paper subaccount, distinct from
    # Eolo bots' subaccount within same Schwab parent account.
    SCHWAB_ACCOUNT_ID: str = ""

    # ── HIGH priority: fail-fast at startup (raise = process cannot start) ───

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError(
                f"DATABASE_URL must start with 'postgresql://' or 'postgres://', got: {v!r}"
            )
        return v

    @field_validator("DB_POOL_MIN")
    @classmethod
    def validate_pool_min(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"DB_POOL_MIN must be >= 1, got {v}")
        return v

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        valid = {"development", "staging", "production"}
        if v not in valid:
            raise ValueError(
                f"ENVIRONMENT must be one of {sorted(valid)}, got {v!r}"
            )
        return v

    @field_validator("TELEGRAM_ALLOWED_CHAT_IDS")
    @classmethod
    def validate_chat_ids(cls, v: str) -> str:
        for part in v.split(","):
            part = part.strip()
            if part:
                try:
                    int(part)
                except ValueError:
                    raise ValueError(
                        f"TELEGRAM_ALLOWED_CHAT_IDS: {part!r} is not a valid integer chat ID"
                    )
        return v

    @model_validator(mode="after")
    def validate_pool_sizes(self) -> "Settings":
        if self.DB_POOL_MIN > self.DB_POOL_MAX:
            raise ValueError(
                f"DB_POOL_MIN ({self.DB_POOL_MIN}) must be <= DB_POOL_MAX "
                f"({self.DB_POOL_MAX}) — check your .env file"
            )
        return self

    @model_validator(mode="after")
    def validate_trading_mode(self) -> "Settings":
        if self.TRADING_MODE == TradingMode.REAL:
            if self.TRADING_MODE_CONFIRM != REAL_MODE_TOKEN:
                raise ValueError(
                    f"{REAL_MODE_HUMAN_MESSAGE}\n"
                    f"To activate, set TRADING_MODE_CONFIRM={REAL_MODE_TOKEN}"
                )
        return self

    # ── WARNING priority: called from lifespan after logging is configured ───

    def log_startup_warnings(self) -> None:
        """
        Emit non-critical config warnings. Call from FastAPI lifespan after
        uvicorn has configured logging so warnings are not silently lost.
        """
        if self.TELEGRAM_BOT_TOKEN and not self.TELEGRAM_ALLOWED_CHAT_IDS:
            logger.warning(
                "Config: TELEGRAM_BOT_TOKEN is set but TELEGRAM_ALLOWED_CHAT_IDS is empty"
                " — all bot commands will be denied (fail-closed)"
            )
        if self.TELEGRAM_BOT_TOKEN and not _TOKEN_RE.match(self.TELEGRAM_BOT_TOKEN):
            logger.warning(
                "Config: TELEGRAM_BOT_TOKEN format looks unexpected "
                "(expected '<8-12 digits>:<35+ chars>')"
            )
        if self.LOG_LEVEL.upper() not in _VALID_LOG_LEVELS:
            logger.warning(
                "Config: LOG_LEVEL=%r is not standard; valid: %s",
                self.LOG_LEVEL,
                sorted(_VALID_LOG_LEVELS),
            )
        if not self.REDIS_URL.startswith(("redis://", "rediss://")):
            logger.warning(
                "Config: REDIS_URL=%r should start with 'redis://' or 'rediss://'",
                self.REDIS_URL,
            )

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def telegram_chat_ids(self) -> list[int]:
        """Parsed list of allowed Telegram chat IDs (validated at startup)."""
        return [int(x.strip()) for x in self.TELEGRAM_ALLOWED_CHAT_IDS.split(",") if x.strip()]

    @property
    def primary_telegram_chat_id(self) -> str | None:
        """First chat ID in the whitelist — primary TelegramSink destination."""
        ids = self.telegram_chat_ids
        return str(ids[0]) if ids else None


settings = Settings()
