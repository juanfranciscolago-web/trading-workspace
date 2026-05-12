"""
FastAPI dependency functions.

All stateful objects (pool, snapshot_builder, limits, buckets, cost_repo)
are stored in app.state during the lifespan and retrieved here.
Test overrides use app.dependency_overrides[<dep_fn>] = lambda: <mock>.
"""
from __future__ import annotations

from fastapi import Request
from claude_router.router import ClaudeRouter

from multi_agent.risk.config import BucketConfig, Phase1Limits
from multi_agent.observability.llm_cost_repository import LLMCostRepository
from multi_agent.alerts.repository import AlertRepository
from multi_agent.persistence.agents_repository import AgentsRepository
from multi_agent.persistence.validation_repository import ValidationRepository
from multi_agent.risk.portfolio_snapshot import CachedSnapshotBuilder
from multi_agent.persistence.system_repository import SystemRepository
from multi_agent.data_layer import DataLayer
from multi_agent.persistence.message_repository import MessageRepository
from multi_agent.communication.message_bus import AgentMessageBus


def get_pool(request: Request):
    return request.app.state.pool


def get_snapshot_builder(request: Request) -> CachedSnapshotBuilder:
    return request.app.state.snapshot_builder


def get_limits(request: Request) -> Phase1Limits:
    return request.app.state.limits


def get_buckets(request: Request) -> BucketConfig:
    return request.app.state.buckets


def get_cost_repo(request: Request) -> LLMCostRepository:
    return request.app.state.cost_repo


def get_validation_repo(request: Request) -> ValidationRepository:
    return ValidationRepository(request.app.state.pool)


def get_alert_repo(request: Request) -> AlertRepository:
    return AlertRepository(request.app.state.pool)


def get_agents_repo(request: Request) -> AgentsRepository:
    return AgentsRepository(request.app.state.pool)


def get_system_repo(request: Request) -> SystemRepository:
    return SystemRepository(request.app.state.pool)


def get_claude_router(request: Request) -> ClaudeRouter:
    return request.app.state.claude_router


def get_data_layer(request: Request) -> DataLayer:
    return request.app.state.data_layer


def get_message_repo(request: Request) -> MessageRepository:
    return MessageRepository(request.app.state.pool)


def get_message_bus(request: Request) -> AgentMessageBus:
    return request.app.state.message_bus
