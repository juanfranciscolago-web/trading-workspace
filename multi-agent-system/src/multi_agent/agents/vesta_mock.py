"""VESTA mock — sector rotation / cross-sectional analyst."""
from __future__ import annotations

import random
from uuid import UUID

from multi_agent.communication.enums import AgentId, Stance
from multi_agent.communication.schemas import (
    CritiqueArgument,
    CritiqueMessage,
    EvidenceItem,
    ProposalMessage,
)

from .base import BaseMockAgent
from .fixtures import ScenarioDef

_AGREE_SUMMARIES = [
    "Sector momentum supports the underlying; rotation not yet reversing.",
    "Sub-industry relative strength is intact — no near-term rotation catalyst.",
]

_DISAGREE_SUMMARIES = [
    "Sector rotation signal turning bearish — capital is moving out of this space.",
    "Sub-industry breadth deteriorating; underlying may lag broader market recovery.",
]

_NEUTRAL_SUMMARIES = [
    "Sector positioning is mid-cycle; no strong rotational edge in either direction.",
]


class VestaMock(BaseMockAgent):
    agent_id = AgentId.VESTA

    def critique(
        self,
        proposal: ProposalMessage,
        scenario: ScenarioDef,
        rng: random.Random,
        correlation_id: UUID,
    ) -> CritiqueMessage:
        stance = scenario.agent_stances.get("vesta", Stance.NEUTRAL)

        if stance == Stance.AGREE:
            summary = rng.choice(_AGREE_SUMMARIES)
            evidence = [
                EvidenceItem(
                    claim="Sector RS rank",
                    data_source="relative_strength_db",
                    value=f"top {rng.randint(10, 25)}%",
                ),
                EvidenceItem(
                    claim="Capital flow",
                    data_source="etf_flows",
                    value=f"+${rng.randint(200, 800)}M last 5 days",
                ),
            ]
            concern = "Watch for sector ETF outflows that could pressure the underlying."
            change_mind = "Sector RS rank drops below 50th percentile or 3-week outflows."
        elif stance == Stance.DISAGREE:
            summary = rng.choice(_DISAGREE_SUMMARIES)
            evidence = [
                EvidenceItem(
                    claim="Sector RS rank",
                    data_source="relative_strength_db",
                    value=f"bottom {rng.randint(30, 50)}%",
                ),
                EvidenceItem(
                    claim="Capital flow",
                    data_source="etf_flows",
                    value=f"-${rng.randint(300, 900)}M last 5 days",
                ),
                EvidenceItem(
                    claim="Breadth signal",
                    data_source="advance_decline",
                    value="deteriorating",
                ),
            ]
            concern = "Sector headwind likely to weigh on IV premium collapse."
            change_mind = "Capital flows reverse positive and RS rank improves."
        else:
            summary = rng.choice(_NEUTRAL_SUMMARIES)
            evidence = [
                EvidenceItem(
                    claim="Sector rotation signal",
                    data_source="rotation_model",
                    value="neutral",
                ),
            ]
            concern = "No clear rotational edge to validate or challenge the thesis."
            change_mind = "Strong directional flow into or out of the sector."

        return CritiqueMessage(
            agent_id=AgentId.VESTA,
            correlation_id=correlation_id,
            parent_message_id=proposal.message_id,
            stance=stance,
            argument=CritiqueArgument(
                summary=summary,
                evidence=evidence,
                concern=concern,
                data_that_would_change_my_mind=change_mind,
            ),
            contrarian_flag_raised="vesta" in scenario.contrarian_agents,
        )
