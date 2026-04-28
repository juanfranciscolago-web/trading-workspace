"""NYX mock — contrarian / narrative asymmetry detector."""
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
    "Consensus narrative aligns with price action; no hidden risk asymmetry detected.",
    "The crowd is not positioned against this trade; no contrarian signal present.",
]

_DISAGREE_SUMMARIES = [
    "Market narrative is too consensus — the setup is crowded and fragile.",
    "Retail options flow is on the same side; this trade will suffer when positioning unwinds.",
    "Analyst optimism has peaked; bad news will be amplified relative to good news.",
]

_NEUTRAL_SUMMARIES = [
    "No clear narrative asymmetry in either direction.",
]


class NyxMock(BaseMockAgent):
    agent_id = AgentId.NYX

    def critique(
        self,
        proposal: ProposalMessage,
        scenario: ScenarioDef,
        rng: random.Random,
        correlation_id: UUID,
    ) -> CritiqueMessage:
        stance = scenario.agent_stances.get("nyx", Stance.NEUTRAL)
        is_contrarian = "nyx" in scenario.contrarian_agents

        if stance == Stance.AGREE:
            summary = rng.choice(_AGREE_SUMMARIES)
            evidence = [
                EvidenceItem(
                    claim="Sentiment survey",
                    data_source="aaii_sentiment",
                    value=f"bears: {rng.randint(35, 45)}%",
                ),
                EvidenceItem(
                    claim="Retail options buying",
                    data_source="options_flow_retail",
                    value="balanced",
                ),
            ]
            concern = "If narrative shifts, IV premium can disappear quickly."
            change_mind = "Retail positioning becomes heavily one-sided."
        elif stance == Stance.DISAGREE:
            summary = rng.choice(_DISAGREE_SUMMARIES)
            evidence = [
                EvidenceItem(
                    claim="Consensus positioning",
                    data_source="cot_report",
                    value=f"net long: {rng.randint(75, 92)}th percentile",
                ),
                EvidenceItem(
                    claim="Analyst upgrades",
                    data_source="bloomberg_consensus",
                    value=f"{rng.randint(80, 95)}% buy ratings — peak optimism",
                ),
                EvidenceItem(
                    claim="Retail call buying",
                    data_source="options_flow_retail",
                    value=f"elevated — top {rng.randint(8, 15)}th percentile",
                ),
            ]
            concern = (
                "The crowd is fully positioned for this outcome. "
                "The trade will underperform if any slight disappointment occurs."
            )
            change_mind = (
                "Institutional positioning rotates away or analyst sentiment diverges."
            )
        else:
            summary = rng.choice(_NEUTRAL_SUMMARIES)
            evidence = [
                EvidenceItem(
                    claim="Narrative asymmetry score",
                    data_source="proprietary_model",
                    value="0.0",
                ),
            ]
            concern = "No actionable contrarian signal."
            change_mind = "Sentiment reaches extreme levels."

        return CritiqueMessage(
            agent_id=AgentId.NYX,
            correlation_id=correlation_id,
            parent_message_id=proposal.message_id,
            stance=stance,
            argument=CritiqueArgument(
                summary=summary,
                evidence=evidence,
                concern=concern,
                data_that_would_change_my_mind=change_mind,
            ),
            contrarian_flag_raised=is_contrarian,
            veto_request=False,
        )
