"""
ATLAS mock — portfolio guardian / risk validator.

Sprint 2A: devuelve AtlasValidationMessage con el nuevo contrato
(approved: bool, executed_size, checks_passed/failed, metrics_snapshot).

Lógica simplificada para tests del orchestrator:
- Escenario atlas_blocks → approved=False, reason=REJECTED_KILL_SWITCH
- Cualquier otro → approved=True con executed_size = proposed_size (o reducido)
"""
from __future__ import annotations

import random
from decimal import Decimal
from uuid import UUID

from multi_agent.communication.enums import AgentId, AtlasReason, RiskMode
from multi_agent.communication.schemas import (
    AtlasValidationMessage,
    DecisionMessage,
    ProposalMessage,
)

from .base import BaseMockAgent
from .fixtures import ScenarioDef

_ATLAS_VERSION = "atlas-mock-1.0"
_NAV_USD = Decimal("1000000.00")
_BASE_BETA = 0.82
_BASE_VEGA = -12400.0
_BASE_BP_PCT = 22.0
_BASE_DRAWDOWN = -2.1


class AtlasMock(BaseMockAgent):
    agent_id = AgentId.ATLAS

    def validate(
        self,
        proposal: ProposalMessage,
        decision: DecisionMessage,
        scenario: ScenarioDef,
        rng: random.Random,
        correlation_id: UUID,
    ) -> AtlasValidationMessage:
        proposed_size = Decimal(str(proposal.sizing.proposed_size_pct_portfolio))

        if scenario.atlas_block:
            return self._build_blocked(proposal, decision, scenario, correlation_id, proposed_size)

        return self._build_approved(proposal, decision, rng, correlation_id, proposed_size)

    def _build_approved(
        self,
        proposal: ProposalMessage,
        decision: DecisionMessage,
        rng: random.Random,
        correlation_id: UUID,
        proposed_size: Decimal,
    ) -> AtlasValidationMessage:
        post_bp = _BASE_BP_PCT + float(proposed_size)
        post_beta = round(_BASE_BETA + rng.uniform(0.01, 0.05), 4)

        metrics = {
            "portfolio.beta_current": _BASE_BETA,
            "portfolio.beta_post": post_beta,
            "portfolio.vega_total_current": _BASE_VEGA,
            "portfolio.buying_power_used_pct": _BASE_BP_PCT,
            "portfolio.drawdown_from_peak_pct": _BASE_DRAWDOWN,
            "portfolio.risk_mode": "GREEN",
            "exposure.post_trade_bp_pct": round(post_bp, 2),
            "stress.spx_down_5pct": {
                "impact_usd": round(-float(_NAV_USD) * _BASE_BETA * 0.05, 2),
                "impact_pct": round(-_BASE_BETA * 5.0, 4),
            },
            "stress.vix_spike_30pct": {
                "impact_usd": round(_BASE_VEGA * 30, 2),
                "impact_pct": round(_BASE_VEGA * 30 / float(_NAV_USD) * 100, 4),
            },
        }

        return AtlasValidationMessage(
            agent_id=AgentId.ATLAS,
            correlation_id=correlation_id,
            parent_message_id=decision.message_id,
            atlas_version=_ATLAS_VERSION,
            approved=True,
            executed_size=proposed_size,
            original_size=proposed_size,
            reason=AtlasReason.APPROVED,
            risk_mode=RiskMode.GREEN,
            checks_passed=[
                "kill_switches", "pnl_halt", "buying_power",
                "single_name", "sector_saturation", "bucket_saturation", "beta",
            ],
            checks_failed=[],
            metrics_snapshot=metrics,
            portfolio_snapshot_id="mock-snapshot-" + str(correlation_id)[:8],
            evaluation_time_ms=round(rng.uniform(1.0, 5.0), 3),
        )

    def _build_blocked(
        self,
        proposal: ProposalMessage,
        decision: DecisionMessage,
        scenario: ScenarioDef,
        correlation_id: UUID,
        proposed_size: Decimal,
    ) -> AtlasValidationMessage:
        block_reason = scenario.atlas_block_reason or AtlasReason.REJECTED_KILL_SWITCH

        metrics = {
            "portfolio.drawdown_from_peak_pct": -26.0,  # past kill switch
            "portfolio.pnl_daily_pct": -9.0,
            "portfolio.risk_mode": "BLACK",
            "limits.drawdown_kill_switch_pct": -25.0,
            "stress.spx_down_5pct": {"impact_usd": -41000.0, "impact_pct": -4.1},
            "stress.vix_spike_30pct": {"impact_usd": -372000.0, "impact_pct": -37.2},
        }

        return AtlasValidationMessage(
            agent_id=AgentId.ATLAS,
            correlation_id=correlation_id,
            parent_message_id=decision.message_id,
            atlas_version=_ATLAS_VERSION,
            approved=False,
            executed_size=Decimal("0"),
            original_size=proposed_size,
            reason=block_reason,
            risk_mode=RiskMode.BLACK,
            checks_passed=[],
            checks_failed=["kill_switches"],
            metrics_snapshot=metrics,
            portfolio_snapshot_id="mock-snapshot-blocked",
            evaluation_time_ms=1.5,
        )
