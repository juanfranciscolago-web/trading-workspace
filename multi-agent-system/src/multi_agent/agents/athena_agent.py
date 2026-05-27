"""
AthenaAgent — real LLM-backed ATHENA agent (Sprint 3 B.3.4).

Integrates the abstract base (B.3.1), data layer (B.3.2), and prompt module
(B.3.3) with ClaudeRouter to produce real proposals.

Flow:
  1. Snapshot market state from the injected data layer.
  2. Build the user prompt embedding that snapshot.
  3. Call ClaudeRouter.send(task_type="proposal_generation", ...).
  4. Parse the LLM response as JSON.
  5. If LLM responds with Shape B ({"no_setup": true, ...}), return None.
  6. Otherwise treat as Shape A: inject agent_id / correlation_id /
     data_signature and validate via ProposalMessage Pydantic.

Errors:
- json.JSONDecodeError if the LLM produces non-JSON. Logged with the
  request_id for tracing in cost/audit logs and re-raised.
- pydantic.ValidationError if Shape A is missing required fields or has
  invalid values. Bubbles up; caller decides whether to retry.

No automatic retries in Sprint 3. If real-LLM testing in B.3.4+ shows
frequent invalid output, add retries via re-prompt-with-error in a
follow-up.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from claude_router.router import ClaudeRouter, Criticality

from multi_agent.communication.enums import AgentId
from multi_agent.communication.schemas import DataSignature, ProposalMessage
from multi_agent.data_layer import DataLayer

from .athena_prompt import SYSTEM_PROMPT, build_user_prompt
from .base_agent import BaseAgent

logger = logging.getLogger(__name__)


class AthenaAgent(BaseAgent):
    """Real ATHENA — generates proposals via LLM and stub/real data layer."""
    agent_id = AgentId.ATHENA

    def __init__(self, claude_router: ClaudeRouter, data_layer: DataLayer) -> None:
        super().__init__(claude_router)
        self._data_layer = data_layer

    def generate_proposal(self, correlation_id: UUID) -> ProposalMessage | None:
        """Run one ATHENA proposal cycle.

        Returns a ProposalMessage when the LLM finds a setup matching ATHENA's
        criteria, or None when the LLM responds with Shape B (no_setup).
        """
        # 1. Snapshot the data layer.
        market_state = self._data_layer.snapshot()

        # 2. Build the user prompt with the snapshot embedded.
        user_prompt = build_user_prompt(market_state)

        # Sprint 12 telemetry-b: Q7/F-r6.5 prompt char count instrumentation.
        logger.info(
            "athena_prompt_metrics",
            extra={
                "event": "athena_prompt_metrics",
                "system_chars": len(SYSTEM_PROMPT),
                "user_chars": len(user_prompt),
                "correlation_id": str(correlation_id),
            },
        )

        # 3. Call the LLM router.
        response = self._claude_router.send(
            task_type="proposal_generation",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            agent=AgentId.ATHENA.value.lower(),
            criticality=Criticality.STANDARD,
        )

        # 4. Parse JSON.
        try:
            parsed = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error(
                "ATHENA LLM returned non-JSON: request_id=%s response.text=%s",
                response.request_id, response.text[:500],
            )
            raise

        # 5. Shape B — no setup found.
        if parsed.get("no_setup") is True:
            logger.info(
                "ATHENA no_setup correlation_id=%s reason=%s",
                correlation_id, parsed.get("reason", "?"),
            )
            return None

        # 6. Shape A — assemble ProposalMessage with system-injected fields.
        proposal = ProposalMessage(
            agent_id=AgentId.ATHENA,
            correlation_id=correlation_id,
            trade=parsed["trade"],
            thesis=parsed["thesis"],
            conviction_score=parsed["conviction_score"],
            sizing=parsed["sizing"],
            self_acknowledged_biases=parsed.get("self_acknowledged_biases", []),
            data_signature=DataSignature(
                # TODO Sprint 5: source from data_layer.name when SchwabDataLayer lands.
                data_sources=["stub_data_layer"],
                data_timestamp=market_state.timestamp,
                model_version="athena-real-v1.0",
            ),
        )
        logger.info(
            "ATHENA proposal generated correlation_id=%s ticker=%s strategy=%s conviction=%d",
            correlation_id,
            proposal.trade.ticker,
            proposal.trade.strategy_type.value,
            proposal.conviction_score,
        )
        return proposal
