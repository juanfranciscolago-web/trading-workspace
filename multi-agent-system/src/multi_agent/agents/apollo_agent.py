"""
ApolloAgent — real LLM-backed APOLLO critic (Sprint 4 B.4.2).

Integrates the abstract base (Sprint 3 B.3.1, extended in B.4.2 with
critique_proposal) and the prompt module (B.4.2) with ClaudeRouter to
produce real critiques of ATHENA proposals.

Sprint 4 scope per ADR-003 D7.2: APOLLO is critic-only — no proposal
generation. generate_proposal is stubbed with NotImplementedError. Future
sprints add APOLLO's full macro generation role per masterdoc §3.2.

Flow:
  1. Receive proposal + market_state + correlation_id from the caller
     (in B.4.5, the worker snapshots data_layer once per cycle and passes
     the same market_state to all critics — APOLLO does no I/O).
  2. Build the user prompt embedding the proposal JSON + market state.
  3. Call ClaudeRouter.send(task_type="cross_examination", ...).
  4. Parse the LLM response as JSON.
  5. Inject agent_id / correlation_id / parent_message_id and validate
     via CritiqueMessage Pydantic.

Errors:
- json.JSONDecodeError if the LLM produces non-JSON. Logged with the
  request_id for tracing in cost/audit logs and re-raised.
- pydantic.ValidationError if the shape is missing fields or has invalid
  values (e.g. unknown stance, evidence with nested-object value).
  Bubbles up; caller decides whether to retry.

No automatic retries in Sprint 4. If real-LLM testing shows frequent
invalid output, add retries via re-prompt-with-error in a follow-up.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from claude_router.router import ClaudeRouter, Criticality

from multi_agent.communication.enums import AgentId
from multi_agent.communication.schemas import CritiqueMessage, ProposalMessage
from multi_agent.data_layer import MarketState

from .apollo_prompt import SYSTEM_PROMPT, build_user_prompt
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class ApolloAgent(BaseAgent):
    """Real APOLLO — critiques ATHENA proposals via LLM under macro lens.

    Sprint 4 role: contrarian/devil's-advocate critic (ADR-003 D7.2).
    Proposal generation deferred to Sprint 5+; generate_proposal is
    stubbed.

    Constructor takes only claude_router — no data_layer. market_state is
    supplied by the caller per critique invocation, so the worker chain
    (B.4.5) can share a single snapshot across all critics.
    """
    agent_id = AgentId.APOLLO

    def generate_proposal(self, correlation_id: UUID) -> ProposalMessage | None:
        """Sprint 4 scope: APOLLO does not generate proposals (ADR-003 D7.2).

        Stubbed to satisfy BaseAgent's abstract method. Future sprints
        implement APOLLO's macro generation role (LEAPs, swing equity,
        crypto spot) per masterdoc §3.2.
        """
        raise NotImplementedError(
            "APOLLO Sprint 4 role is critique-only (ADR-003 D7.2). "
            "Proposal generation deferred to Sprint 5+."
        )

    def critique_proposal(
        self,
        proposal: ProposalMessage,
        market_state: MarketState,
        correlation_id: UUID,
    ) -> CritiqueMessage:
        """Critique a proposal under macro lens, producing a CritiqueMessage.

        market_state is supplied by the caller; APOLLO performs no I/O
        itself — pure transformation from (proposal, market_state) to
        CritiqueMessage via the LLM.
        """
        # 1. Build the user prompt with proposal + market state embedded.
        user_prompt = build_user_prompt(proposal, market_state)

        # 2. Call the LLM router.
        response = self._claude_router.send(
            task_type="cross_examination",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            agent=AgentId.APOLLO.value.lower(),
            criticality=Criticality.STANDARD,
        )

        # 3. Parse JSON.
        try:
            parsed = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error(
                "APOLLO LLM returned non-JSON: request_id=%s response.text=%s",
                response.request_id, response.text[:500],
            )
            raise

        # 4. Assemble CritiqueMessage with system-injected fields.
        critique = CritiqueMessage(
            agent_id=AgentId.APOLLO,
            correlation_id=correlation_id,
            parent_message_id=proposal.message_id,
            stance=parsed["stance"],
            argument=parsed["argument"],
            veto_request=parsed.get("veto_request", False),
            contrarian_flag_raised=parsed.get("contrarian_flag_raised", False),
            alternative_proposal=parsed.get("alternative_proposal"),
        )
        logger.info(
            "APOLLO critique generated correlation_id=%s stance=%s veto=%s contrarian=%s",
            correlation_id,
            critique.stance.value,
            critique.veto_request,
            critique.contrarian_flag_raised,
        )
        return critique
