"""HERMES mock — tactical flow / short-term momentum."""
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
    "Short-term order flow is net-selling premium; IV crush likely within 2 weeks.",
    "Options market-maker positioning supports IV contraction; trade timing is good.",
]

_DISAGREE_SUMMARIES = [
    "Dealer gamma flipping tomorrow — intraday vol likely to spike; wait for entry.",
    "GEX levels suggest a move outside expected range is possible this week.",
]

_NEUTRAL_SUMMARIES = [
    "No strong near-term flow signal; tactical edge is flat.",
]


class HermesMock(BaseMockAgent):
    agent_id = AgentId.HERMES

    def critique(
        self,
        proposal: ProposalMessage,
        scenario: ScenarioDef,
        rng: random.Random,
        correlation_id: UUID,
    ) -> CritiqueMessage:
        stance = scenario.agent_stances.get("hermes", Stance.NEUTRAL)

        if stance == Stance.AGREE:
            summary = rng.choice(_AGREE_SUMMARIES)
            evidence = [
                EvidenceItem(
                    claim="Put/call ratio",
                    data_source="cboe_flow",
                    value=round(rng.uniform(0.65, 0.85), 2),
                ),
                EvidenceItem(
                    claim="GEX",
                    data_source="spot_gamma",
                    value=f"+{rng.randint(1, 3)}B",
                ),
            ]
            concern = "Entry is good now; avoid chasing if price moves more than 1%."
            change_mind = "Gamma flip to negative or put/call ratio spikes above 1.0."
        elif stance == Stance.DISAGREE:
            summary = rng.choice(_DISAGREE_SUMMARIES)
            evidence = [
                EvidenceItem(
                    claim="GEX level",
                    data_source="spot_gamma",
                    value="negative gamma: dealer short",
                ),
                EvidenceItem(
                    claim="Skew",
                    data_source="cboe_skew",
                    value=f"put skew elevated +{rng.randint(3, 8)}%",
                ),
            ]
            concern = "Short-term vol spike risk; premium may not be sufficient."
            change_mind = "GEX turns positive and put skew normalizes."
        else:
            summary = rng.choice(_NEUTRAL_SUMMARIES)
            evidence = [
                EvidenceItem(
                    claim="Tactical flow signal",
                    data_source="composite_flow",
                    value="neutral",
                ),
            ]
            concern = "No flow edge to add to the thesis."
            change_mind = "Clear directional flow signal emerges."

        return CritiqueMessage(
            agent_id=AgentId.HERMES,
            correlation_id=correlation_id,
            parent_message_id=proposal.message_id,
            stance=stance,
            argument=CritiqueArgument(
                summary=summary,
                evidence=evidence,
                concern=concern,
                data_that_would_change_my_mind=change_mind,
            ),
            contrarian_flag_raised="hermes" in scenario.contrarian_agents,
        )
