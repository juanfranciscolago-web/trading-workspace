"""
ATLAS mock — portfolio guardian / risk validator.

Validates the consensus decision against mock portfolio state.
In the atlas_blocks scenario, sets AtlasDecision.BLOCKED regardless
of the consensus outcome.
"""
from __future__ import annotations

import random
from decimal import Decimal
from uuid import UUID

from multi_agent.communication.enums import AgentId, AtlasDecision, DecisionOutcome, RiskMode
from multi_agent.communication.schemas import (
    AtlasValidationMessage,
    DecisionMessage,
    LimitDistances,
    PortfolioImpact,
    PortfolioState,
    ProposalMessage,
    StressTestResult,
)

from .base import BaseMockAgent
from .fixtures import ScenarioDef

# Static mock portfolio baseline
_BASE_BETA = 0.82
_BASE_TECH_CONCENTRATION = 38.5
_BASE_VEGA_TOTAL = 12_400.0
_BASE_DRAWDOWN = -2.1
_BASE_BUYING_POWER_USED = 22.0


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
        # ── determine risk mode ────────────────────────────────────────────────
        if scenario.atlas_block:
            risk_mode = RiskMode.YELLOW
            atlas_decision = AtlasDecision.BLOCKED
            modulations = [scenario.atlas_block_reason]
            buying_power_post = scenario.buying_power_used_pct + float(
                proposal.sizing.proposed_size_pct_portfolio
            )
            tech_conc_post = _BASE_TECH_CONCENTRATION + float(
                proposal.sizing.proposed_size_pct_portfolio
            )
        else:
            risk_mode = RiskMode.GREEN
            buying_power_post = _BASE_BUYING_POWER_USED + float(
                proposal.sizing.proposed_size_pct_portfolio
            )
            tech_conc_post = _BASE_TECH_CONCENTRATION + float(
                proposal.sizing.proposed_size_pct_portfolio * 0.6
            )
            modulations = []

            if decision.outcome == DecisionOutcome.APPROVED:
                atlas_decision = AtlasDecision.APPROVED
            else:
                atlas_decision = AtlasDecision.APPROVED_WITH_CONDITIONS
                if decision.size_modulation:
                    modulations.append(
                        f"Size validated at {decision.size_modulation.approved_size_pct:.1f}%"
                    )

        current_state = PortfolioState(
            portfolio_beta=_BASE_BETA,
            tech_concentration_pct=_BASE_TECH_CONCENTRATION,
            vega_total=_BASE_VEGA_TOTAL,
            drawdown_from_peak_pct=_BASE_DRAWDOWN,
            buying_power_used_pct=_BASE_BUYING_POWER_USED,
        )
        post_state = PortfolioState(
            portfolio_beta=round(_BASE_BETA + rng.uniform(0.01, 0.05), 4),
            tech_concentration_pct=round(tech_conc_post, 2),
            vega_total=_BASE_VEGA_TOTAL + rng.uniform(800, 2000),
            drawdown_from_peak_pct=_BASE_DRAWDOWN,
            buying_power_used_pct=round(min(buying_power_post, 95.0), 2),
        )
        limit_distances = LimitDistances(
            tech_concentration_limit=45.0,
            distance_to_limit_pct=round(45.0 - post_state.tech_concentration_pct, 2),
            vega_limit=50_000.0,
            distance_to_vega_limit_pct=round(
                (50_000.0 - post_state.vega_total) / 50_000.0 * 100, 2
            ),
        )

        stress_tests = [
            StressTestResult(
                scenario="market_down_5pct",
                projected_pl_usd=round(-float(proposal.sizing.proposed_size_usd) * 0.08, 2),
                projected_pl_pct=round(-0.08, 4),
            ),
            StressTestResult(
                scenario="iv_spike_30pct",
                projected_pl_usd=round(-float(proposal.sizing.proposed_size_usd) * 0.12, 2),
                projected_pl_pct=round(-0.12, 4),
            ),
            StressTestResult(
                scenario="black_swan_down_15pct",
                projected_pl_usd=round(-float(proposal.sizing.proposed_size_usd) * 0.25, 2),
                projected_pl_pct=round(-0.25, 4),
            ),
        ]

        return AtlasValidationMessage(
            agent_id=AgentId.ATLAS,
            correlation_id=correlation_id,
            parent_message_id=decision.message_id,
            decision=atlas_decision,
            portfolio_impact=PortfolioImpact(
                current_state=current_state,
                post_trade_state=post_state,
                limit_distances=limit_distances,
            ),
            stress_test_results=stress_tests,
            modulations_applied=modulations,
            risk_mode=risk_mode,
        )
