from __future__ import annotations

import logging
from uuid import UUID, uuid4

from claude_router.router import ClaudeRouter
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from multi_agent.agents.athena_agent import AthenaAgent
from multi_agent.api.dependencies import (
    get_agents_repo,
    get_claude_router,
    get_data_layer,
    get_message_bus,
    get_message_repo,
)
from multi_agent.api.schemas.responses import AgentItem, AgentsListResponse
from multi_agent.communication.message_bus import AgentChannels, AgentMessageBus
from multi_agent.communication.schemas import ProposalMessage
from multi_agent.data_layer import DataLayer
from multi_agent.persistence.agents_repository import AgentsRepository
from multi_agent.persistence.message_repository import MessageRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class ToggleAgentRequest(BaseModel):
    is_active: bool


class ToggleAgentResponse(BaseModel):
    agent_id: str
    is_active: bool


class TriggerAthenaResponse(BaseModel):
    """Result of POST /agents/athena/trigger.

    `proposal` is the generated proposal when ATHENA finds a setup, or None
    when ATHENA declines (no_setup=True). `correlation_id` is generated
    server-side per call.
    """
    correlation_id: UUID
    proposal: ProposalMessage | None
    no_setup: bool


@router.get("", response_model=AgentsListResponse)
def list_agents(
    repo: AgentsRepository = Depends(get_agents_repo),
) -> AgentsListResponse:
    """List all agents with their config and runtime state."""
    rows = repo.list_agents()
    items = [AgentItem(**row) for row in rows]
    return AgentsListResponse(items=items)


@router.post("/{agent_id}/toggle", response_model=ToggleAgentResponse)
def toggle_agent(
    agent_id: str,
    body: ToggleAgentRequest,
    repo: AgentsRepository = Depends(get_agents_repo),
) -> ToggleAgentResponse:
    """Set agent is_active flag explicitly. Returns 404 if agent not found."""
    updated = repo.set_active(agent_id, body.is_active)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_id}' not found",
        )
    logger.info("agent_toggled agent_id=%s is_active=%s", agent_id, body.is_active)
    return ToggleAgentResponse(agent_id=agent_id, is_active=body.is_active)


@router.post("/athena/trigger", response_model=TriggerAthenaResponse)
def trigger_athena(
    claude_router: ClaudeRouter = Depends(get_claude_router),
    data_layer: DataLayer = Depends(get_data_layer),
    message_repo: MessageRepository = Depends(get_message_repo),
    bus: AgentMessageBus = Depends(get_message_bus),
) -> TriggerAthenaResponse:
    """Trigger ATHENA to generate one proposal from current market state.

    Returns the proposal if ATHENA finds a setup, or no_setup=True if
    ATHENA declines (Shape B). When a proposal is found, it is persisted to
    trades.proposals AND published to agent.proposals bus so the downstream
    worker chain (APOLLO critic, ConsensusEngine, ATLAS validator) can pick
    it up. No persistence or publish on no_setup.

    Synchronous up to the publish step (ATHENA LLM call: 5-30s, then DB
    insert + Redis XADD). Returns once the proposal is on the bus. The
    workers consume asynchronously and transition proposal.status
    independently — the caller polls to observe pipeline progress.

    The publish step is fail-loud (Sprint 4 B.4.4 decision D-a): if Redis
    is unavailable, the exception bubbles up as a 500. The proposal will
    be in the DB but not on the bus; the operator decides whether to
    retry the trigger or treat the proposal as orphan. This is intentional
    — silent-publish-failure would leave proposals dangling forever.

    Sprint 3 debate-only: ATLAS validation flows downstream but no execution.
    """
    correlation_id = uuid4()
    logger.info("athena_trigger_start correlation_id=%s", correlation_id)

    agent = AthenaAgent(claude_router, data_layer)
    proposal = agent.generate_proposal(correlation_id)

    if proposal is None:
        logger.info("athena_trigger_no_setup correlation_id=%s", correlation_id)
        return TriggerAthenaResponse(
            correlation_id=correlation_id,
            proposal=None,
            no_setup=True,
        )

    message_repo.save_proposal(proposal)
    bus.publish(AgentChannels.PROPOSALS, proposal)
    logger.info(
        "athena_trigger_persisted_and_published correlation_id=%s ticker=%s",
        correlation_id, proposal.trade.ticker,
    )
    return TriggerAthenaResponse(
        correlation_id=correlation_id,
        proposal=proposal,
        no_setup=False,
    )
