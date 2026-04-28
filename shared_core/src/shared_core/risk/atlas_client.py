"""
ATLAS Risk Validation Client — used by BOTH Eolo and the multi-agent system.

This is the critical piece for cross-system risk coordination. Before any
trade is executed (regardless of which system originated it), it MUST go
through atlas_client.validate_trade().

ATLAS sees the aggregate portfolio (Eolo positions + multi-agent positions +
human trades) and applies unified risk limits. Without this, two systems
operating on the same account can create hidden concentration.

Architecture:
    The actual ATLAS engine runs as a service in the multi-agent system.
    This client is a thin wrapper that talks to it via HTTP/Redis.

    Eolo imports this client and calls validate_trade() before every order.
    Multi-agent imports it too (cleaner than direct internal calls).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from shared_core.models import Direction, Instrument, TradeOrder, TradeSource

logger = logging.getLogger(__name__)


class RiskDecision(str, Enum):
    """ATLAS verdict on a proposed trade."""
    APPROVED = "approved"
    APPROVED_WITH_CONDITIONS = "approved_with_conditions"
    BLOCKED = "blocked"


class RiskMode(str, Enum):
    """Current operational mode of ATLAS."""
    GREEN = "green"      # Normal operation
    YELLOW = "yellow"    # Elevated alert
    RED = "red"          # Defensive mode
    BLACK = "black"      # Crisis mode


@dataclass
class RiskCondition:
    """A condition attached to an APPROVED_WITH_CONDITIONS decision."""
    type: str  # "size_reduction", "tighter_stop", "time_stop", "hedge_required", "watch_flag"
    description: str
    parameter: Optional[dict] = None


@dataclass
class RiskCheck:
    """Response from ATLAS on a proposed trade."""
    decision: RiskDecision
    risk_mode: RiskMode
    timestamp: datetime
    reason: str

    # If approved with conditions, these apply
    conditions: list[RiskCondition] = field(default_factory=list)
    modified_size: Optional[int] = None  # If ATLAS modulates size

    # Diagnostic info
    portfolio_state: dict = field(default_factory=dict)
    limit_breaches: list[str] = field(default_factory=list)
    stress_test_results: list[dict] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.decision == RiskDecision.APPROVED

    @property
    def approved_with_conditions(self) -> bool:
        return self.decision == RiskDecision.APPROVED_WITH_CONDITIONS

    @property
    def blocked(self) -> bool:
        return self.decision == RiskDecision.BLOCKED


class AtlasClient:
    """
    Client for the ATLAS risk validation service.

    Both Eolo and multi-agent agents use this before placing any trade.
    """

    def __init__(
        self,
        atlas_endpoint: str = "http://localhost:8001",
        timeout_seconds: float = 5.0,
        fail_open: bool = False,
    ):
        """
        Args:
            atlas_endpoint: URL of ATLAS service
            timeout_seconds: Max wait for ATLAS response
            fail_open: If True, approve when ATLAS is unreachable (DANGEROUS).
                       Default False — fail closed for safety.
        """
        self.endpoint = atlas_endpoint
        self.timeout = timeout_seconds
        self.fail_open = fail_open

    def validate_trade(
        self,
        order: TradeOrder,
        thesis: Optional[str] = None,
    ) -> RiskCheck:
        """
        Validate a proposed trade against current portfolio state.

        This is the critical gate. Both Eolo and multi-agent MUST call this
        before executing any trade.

        Args:
            order: The proposed trade
            thesis: Optional explanation (for logging/audit)

        Returns:
            RiskCheck with decision and (if approved with conditions)
            specific modifications to apply.
        """
        request_payload = self._build_request(order, thesis)

        try:
            response = self._call_atlas(request_payload)
            return self._parse_response(response)
        except Exception as e:
            logger.error(f"ATLAS validation failed: {e}")

            if self.fail_open:
                logger.warning(
                    "fail_open=True — approving trade despite ATLAS failure. "
                    "REVIEW: this is risky behavior."
                )
                return RiskCheck(
                    decision=RiskDecision.APPROVED,
                    risk_mode=RiskMode.GREEN,
                    timestamp=datetime.now(timezone.utc),
                    reason="ATLAS unreachable, fail_open=True",
                )
            else:
                # Fail closed: block the trade
                return RiskCheck(
                    decision=RiskDecision.BLOCKED,
                    risk_mode=RiskMode.GREEN,  # Unknown
                    timestamp=datetime.now(timezone.utc),
                    reason=f"ATLAS unreachable: {e}. Failing closed for safety.",
                )

    def get_portfolio_state(self) -> dict:
        """
        Get current aggregate portfolio state from ATLAS.

        Useful for Eolo to query exposure before deciding what to trade.
        Returns dict with: positions, greeks_aggregate, sector_exposure,
        beta_net, drawdown_from_peak, current_mode, etc.
        """
        try:
            return self._call_atlas_endpoint("/portfolio/state", method="GET")
        except Exception as e:
            logger.error(f"Failed to fetch portfolio state: {e}")
            return {}

    def get_current_mode(self) -> RiskMode:
        """Quick check of ATLAS current mode (Green/Yellow/Red/Black)."""
        try:
            response = self._call_atlas_endpoint("/mode", method="GET")
            return RiskMode(response.get("mode", "green"))
        except Exception:
            return RiskMode.GREEN  # Optimistic default

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _build_request(
        self,
        order: TradeOrder,
        thesis: Optional[str],
    ) -> dict:
        """Construct the validation request payload."""
        return {
            "source": order.source.value,
            "instrument": order.instrument.to_dict(),
            "direction": order.direction.value,
            "quantity": order.quantity,
            "expected_price": float(order.expected_price) if order.expected_price else None,
            "strategy": order.strategy,
            "thesis": thesis,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _call_atlas(self, payload: dict) -> dict:
        """
        Make HTTP call to ATLAS validation endpoint.

        TODO: Replace this stub with actual HTTP client (httpx).
        Recommended: use httpx with retries and timeout.
        """
        # Placeholder — actual implementation:
        # import httpx
        # response = httpx.post(
        #     f"{self.endpoint}/validate",
        #     json=payload,
        #     timeout=self.timeout,
        # )
        # response.raise_for_status()
        # return response.json()
        raise NotImplementedError("Implement HTTP call to ATLAS service")

    def _call_atlas_endpoint(self, path: str, method: str = "GET", payload: dict = None) -> dict:
        """Generic ATLAS endpoint caller."""
        # TODO: Implement
        raise NotImplementedError("Implement HTTP client")

    def _parse_response(self, response: dict) -> RiskCheck:
        """Parse ATLAS response into RiskCheck object."""
        return RiskCheck(
            decision=RiskDecision(response["decision"]),
            risk_mode=RiskMode(response.get("risk_mode", "green")),
            timestamp=datetime.fromisoformat(response["timestamp"]),
            reason=response.get("reason", ""),
            conditions=[
                RiskCondition(**c) for c in response.get("conditions", [])
            ],
            modified_size=response.get("modified_size"),
            portfolio_state=response.get("portfolio_state", {}),
            limit_breaches=response.get("limit_breaches", []),
            stress_test_results=response.get("stress_test_results", []),
        )


# =============================================================================
# Convenience: singleton accessor
# =============================================================================

_global_atlas_client: Optional[AtlasClient] = None


def get_atlas_client(
    endpoint: Optional[str] = None,
    fail_open: bool = False,
) -> AtlasClient:
    """Get or initialize the global ATLAS client."""
    global _global_atlas_client
    if _global_atlas_client is None:
        import os
        endpoint = endpoint or os.environ.get("ATLAS_ENDPOINT", "http://localhost:8001")
        _global_atlas_client = AtlasClient(
            atlas_endpoint=endpoint,
            fail_open=fail_open,
        )
    return _global_atlas_client


def reset_atlas_client() -> None:
    """Reset singleton (mainly for testing)."""
    global _global_atlas_client
    _global_atlas_client = None
