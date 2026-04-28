from __future__ import annotations

from enum import Enum

# Re-export canonical enums from shared_core (option C — single source of truth)
from shared_core.models import AssetClass, Direction, OptionType, TradeSource, TradeStatus

__all__ = [
    # Re-exported from shared_core
    "AssetClass",
    "Direction",
    "OptionType",
    "TradeSource",
    "TradeStatus",
    # Multi-agent protocol enums
    "MessageType",
    "AgentId",
    "StrategyType",
    "Stance",
    "DecisionOutcome",
    "ConsensusType",
    "AtlasDecision",
    "RiskMode",
    "TradeResult",
]


class MessageType(str, Enum):
    PROPOSAL = "PROPOSAL"
    CRITIQUE = "CRITIQUE"
    DECISION = "DECISION"
    ATLAS_VALIDATION = "ATLAS_VALIDATION"
    EXECUTION = "EXECUTION"
    POSTMORTEM = "POSTMORTEM"
    ALERT = "ALERT"


class AgentId(str, Enum):
    ATHENA = "ATHENA"
    APOLLO = "APOLLO"
    HERMES = "HERMES"
    NYX = "NYX"
    ATLAS = "ATLAS"
    VESTA = "VESTA"


class StrategyType(str, Enum):
    CSP = "CSP"
    COVERED_CALL = "COVERED_CALL"
    CREDIT_SPREAD = "CREDIT_SPREAD"
    DEBIT_SPREAD = "DEBIT_SPREAD"
    IRON_CONDOR = "IRON_CONDOR"
    LEAP = "LEAP"
    CALENDAR = "CALENDAR"
    SWING_EQUITY = "SWING_EQUITY"
    CRYPTO_SPOT = "CRYPTO_SPOT"
    ZERO_DTE = "ZERO_DTE"
    WEEKLY = "WEEKLY"
    SECTOR_ROTATION = "SECTOR_ROTATION"


class Stance(str, Enum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"
    NEUTRAL = "NEUTRAL"
    AGREE_WITH_CONDITIONS = "AGREE_WITH_CONDITIONS"


class DecisionOutcome(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    REJECTED = "REJECTED"


class ConsensusType(str, Enum):
    UNANIMOUS = "UNANIMOUS"
    MAJORITY = "MAJORITY"
    MAJORITY_WITH_PRODUCTIVE_DISAGREEMENT = "MAJORITY_WITH_PRODUCTIVE_DISAGREEMENT"
    SPLIT = "SPLIT"
    NO_QUORUM = "NO_QUORUM"


class AtlasDecision(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    BLOCKED = "BLOCKED"


class RiskMode(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    BLACK = "BLACK"


class TradeResult(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    BREAKEVEN = "BREAKEVEN"
    STOP_OUT = "STOP_OUT"
