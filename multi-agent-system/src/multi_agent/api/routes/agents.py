from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from multi_agent.api.dependencies import get_agents_repo
from multi_agent.api.schemas.responses import AgentItem, AgentsListResponse
from multi_agent.persistence.agents_repository import AgentsRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])


class ToggleAgentRequest(BaseModel):
    is_active: bool


class ToggleAgentResponse(BaseModel):
    agent_id: str
    is_active: bool


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
