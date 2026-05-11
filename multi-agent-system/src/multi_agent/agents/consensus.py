"""
Phase 3 consensus engine.

Evaluates a list of critiques against the original proposal and
produces a DecisionMessage. Rules (in priority order):

  Veto (≥1 veto_request=True)                 → REJECTED, VETOED, size=None,
                                                  conditions=["vetoed_by:{agent}", ...]
  Unanimous (4/4 AGREE)                       → APPROVED, full size
  Majority (3+ effective agree, 0 disagree)   → APPROVED, full size
  Productive dissent (3+ agree, 1 DISAGREE
    with contrarian_flag)                      → APPROVED_WITH_CONDITIONS, 50% size
  Majority with plain dissent (3+ agree, 1
    DISAGREE, no contrarian flag)              → APPROVED, full size
  Split (≤2 agree, ≥2 disagree)               → REJECTED
  No quorum (all NEUTRAL), conviction ≥ 90    → APPROVED_WITH_CONDITIONS, 33% size
  No quorum (all NEUTRAL), conviction < 90    → DEFERRED

Every branch propagates contrarian_flag_raised = any(c.contrarian_flag_raised
for c in critiques) to the DecisionMessage so ATLAS and the operator see
the signal even when consensus-level rules dilute it (e.g. plain majority
overriding a contrarian dissent).
"""
from __future__ import annotations

from uuid import UUID

from multi_agent.communication.enums import (
    AgentId,
    ConsensusType,
    DecisionOutcome,
    Stance,
)
from multi_agent.communication.schemas import (
    ConsensusState,
    CritiqueMessage,
    DecisionMessage,
    ProposalMessage,
    SizeModulation,
)


def evaluate(
    proposal: ProposalMessage,
    critiques: list[CritiqueMessage],
    correlation_id: UUID,
) -> DecisionMessage:
    agree_ids: list[AgentId] = []
    disagree_ids: list[AgentId] = []
    neutral_ids: list[AgentId] = []
    contrarian_disagree_ids: list[AgentId] = []
    veto_ids: list[AgentId] = []

    for c in critiques:
        if c.veto_request:
            veto_ids.append(c.agent_id)
        if c.stance in (Stance.AGREE, Stance.AGREE_WITH_CONDITIONS):
            agree_ids.append(c.agent_id)
        elif c.stance == Stance.DISAGREE:
            disagree_ids.append(c.agent_id)
            if c.contrarian_flag_raised:
                contrarian_disagree_ids.append(c.agent_id)
        else:
            neutral_ids.append(c.agent_id)

    n_agree = len(agree_ids)
    n_disagree = len(disagree_ids)
    n_neutral = len(neutral_ids)
    n_total = len(critiques)
    proposed_pct = proposal.sizing.proposed_size_pct_portfolio
    contrarian_flag_raised = any(c.contrarian_flag_raised for c in critiques)

    # ── Determine consensus type and outcome ──────────────────────────────────

    if veto_ids:
        # Veto wins regardless of vote distribution. ATLAS sees the veto list
        # via conditions; consensus_state retains the full vote tally for audit.
        consensus_type = ConsensusType.VETOED
        outcome = DecisionOutcome.REJECTED
        approved_pct = 0.0
        conditions = [f"vetoed_by:{a.value}" for a in veto_ids]
        size_modulation = None

    elif n_agree == n_total:
        consensus_type = ConsensusType.UNANIMOUS
        outcome = DecisionOutcome.APPROVED
        approved_pct = proposed_pct
        conditions: list[str] = []
        size_modulation = None

    elif n_agree >= 3 and n_disagree == 0:
        consensus_type = ConsensusType.MAJORITY
        outcome = DecisionOutcome.APPROVED
        approved_pct = proposed_pct
        conditions = []
        size_modulation = None

    elif n_agree >= 3 and contrarian_disagree_ids:
        # Productive dissent: contrarian flag raises a meaningful counter-thesis
        consensus_type = ConsensusType.MAJORITY_WITH_PRODUCTIVE_DISAGREEMENT
        outcome = DecisionOutcome.APPROVED_WITH_CONDITIONS
        approved_pct = round(proposed_pct * 0.50, 2)
        dissenter_names = ", ".join(a.value for a in contrarian_disagree_ids)
        conditions = [
            f"Size reduced to 50% due to contrarian disagreement from {dissenter_names}",
            "Monitor invalidation triggers more closely",
        ]
        size_modulation = SizeModulation(
            original_size_pct=proposed_pct,
            approved_size_pct=approved_pct,
            reduction_reason=f"Productive contrarian dissent from {dissenter_names}",
        )

    elif n_agree >= 3 and n_disagree > 0:
        # Plain majority with non-contrarian dissent
        consensus_type = ConsensusType.MAJORITY
        outcome = DecisionOutcome.APPROVED
        approved_pct = proposed_pct
        conditions = []
        size_modulation = None

    elif n_neutral == n_total:
        # No quorum — high conviction solo approval rule
        consensus_type = ConsensusType.NO_QUORUM
        if proposal.conviction_score >= 90:
            outcome = DecisionOutcome.APPROVED_WITH_CONDITIONS
            approved_pct = round(proposed_pct * 0.33, 2)
            conditions = [
                "Solo conviction approval: no quorum from critiquing agents",
                "Size capped at 33% of proposed",
            ]
            size_modulation = SizeModulation(
                original_size_pct=proposed_pct,
                approved_size_pct=approved_pct,
                reduction_reason=(
                    f"No critic quorum; solo approval on conviction={proposal.conviction_score}"
                ),
            )
        else:
            outcome = DecisionOutcome.DEFERRED
            approved_pct = 0.0
            conditions = ["Deferred: no quorum and conviction below 90"]
            size_modulation = None

    else:
        # Split or minority agree
        consensus_type = ConsensusType.SPLIT
        outcome = DecisionOutcome.REJECTED
        approved_pct = 0.0
        conditions = [
            f"Split vote: {n_agree} agree vs {n_disagree} disagree "
            f"({n_neutral} neutral) — insufficient consensus"
        ]
        size_modulation = None

    consensus_state = ConsensusState(
        agree=agree_ids,
        disagree=disagree_ids,
        neutral=neutral_ids,
        consensus_type=consensus_type,
    )

    return DecisionMessage(
        agent_id=AgentId.ATLAS,  # orchestrator role
        correlation_id=correlation_id,
        parent_message_id=proposal.message_id,
        outcome=outcome,
        consensus_state=consensus_state,
        size_modulation=size_modulation,
        conditions=conditions,
        contrarian_flag_raised=contrarian_flag_raised,
    )
