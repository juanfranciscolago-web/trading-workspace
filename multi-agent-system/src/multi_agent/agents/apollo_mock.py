"""APOLLO mock — macro discrecional."""
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
    "Macro backdrop supports premium-selling: low vol regime expected to persist.",
    "Risk/reward ratio is favorable; broader market trend aligns with thesis.",
    "Fed posture and earnings calendar make this window suitable for the trade.",
]

_DISAGREE_SUMMARIES = [
    "Macro uncertainty too high — upcoming FOMC could spike volatility materially.",
    "Sector rotation away from tech weakens the underlying bid; IV may not collapse.",
]

_NEUTRAL_SUMMARIES = [
    "Insufficient macro catalyst data to form a strong view either way.",
    "Mixed signals from leading indicators; deferring to quantitative edge.",
]


class ApolloMock(BaseMockAgent):
    agent_id = AgentId.APOLLO

    def critique(
        self,
        proposal: ProposalMessage,
        scenario: ScenarioDef,
        rng: random.Random,
        correlation_id: UUID,
    ) -> CritiqueMessage:
        stance = scenario.agent_stances.get("apollo", Stance.NEUTRAL)

        if stance == Stance.AGREE:
            summary = rng.choice(_AGREE_SUMMARIES)
            evidence = [
                EvidenceItem(claim="VIX below 20", data_source="cboe", value=round(rng.uniform(15, 19), 1)),
                EvidenceItem(claim="SPX trend", data_source="price_action", value="bullish"),
            ]
            concern = "Watch for FOMC surprises within DTE window."
            change_mind = "VIX spike above 25 or gap in earnings calendar."
        elif stance == Stance.DISAGREE:
            summary = rng.choice(_DISAGREE_SUMMARIES)
            evidence = [
                EvidenceItem(claim="FOMC meeting within DTE", data_source="fed_calendar", value=True),
                EvidenceItem(claim="Credit spreads widening", data_source="bloomberg", value="HY OAS +45bps"),
            ]
            concern = "Macro headwinds likely to elevate vol; premium insufficient."
            change_mind = "FOMC meeting moved outside DTE or credit spreads stabilize."
        else:
            summary = rng.choice(_NEUTRAL_SUMMARIES)
            evidence = [
                EvidenceItem(claim="Macro signal strength", data_source="composite_index", value="neutral"),
            ]
            concern = "No strong macro thesis to add or subtract."
            change_mind = "Directional macro catalyst materializes."

        return CritiqueMessage(
            agent_id=AgentId.APOLLO,
            correlation_id=correlation_id,
            parent_message_id=proposal.message_id,
            stance=stance,
            argument=CritiqueArgument(
                summary=summary,
                evidence=evidence,
                concern=concern,
                data_that_would_change_my_mind=change_mind,
            ),
            contrarian_flag_raised="apollo" in scenario.contrarian_agents,
        )
