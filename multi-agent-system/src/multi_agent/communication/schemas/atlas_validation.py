"""
AtlasValidationMessage — contrato Sprint 2A.

Cambio de schema respecto a Sprint 1:
- approved: bool reemplaza AtlasDecision enum en el mensaje
- executed_size / original_size expresan la decisión de sizing de ATLAS
- metrics_snapshot dict reemplaza los nested models PortfolioImpact/PortfolioState
- stress tests van en metrics_snapshot["stress.*"]
- risk_mode se mantiene como campo de primer nivel (semántica operacional)
- checks_passed / checks_failed dan trazabilidad de la decisión
- portfolio_snapshot_id vincula con atlas.portfolio_snapshots
- evaluation_time_ms para monitoreo de performance

Los modelos legados (PortfolioState, PortfolioImpact, LimitDistances, StressTestResult)
se mantienen en este módulo como deprecated hasta que se complete la migración de
trades.atlas_validations (Sprint 3+).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from ..base import BaseMessage
from ..enums import MessageType, RiskMode


class AtlasValidationMessage(BaseMessage):
    """Resultado de la validación de ATLAS sobre un trade aprobado por consenso."""

    message_type: Literal[MessageType.ATLAS_VALIDATION] = MessageType.ATLAS_VALIDATION

    # ── Versioning ─────────────────────────────────────────────────────────────
    atlas_version: str = Field(description="Versión del motor ATLAS que emitió esta validación")

    # ── Decisión de ejecución ──────────────────────────────────────────────────
    approved: bool = Field(description="True si ATLAS aprueba ejecución (executed_size > 0)")
    executed_size: Decimal = Field(ge=0, description="Tamaño a ejecutar en % del portfolio")
    original_size: Decimal = Field(gt=0, description="Tamaño propuesto originalmente")

    # ── Razón (convención 'category:detail') ──────────────────────────────────
    reason: str = Field(description="AtlasReason constant — ver communication.enums.AtlasReason")

    # ── Estado operacional ─────────────────────────────────────────────────────
    risk_mode: RiskMode = Field(description="Estado operacional de ATLAS al momento de la validación")

    # ── Trazabilidad de checks ─────────────────────────────────────────────────
    checks_passed: list[str] = Field(default_factory=list)
    checks_failed: list[str] = Field(default_factory=list)

    # ── Métricas del portfolio ─────────────────────────────────────────────────
    metrics_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Métricas namespaceadas del portfolio al momento de la validación. "
            "Namespaces: portfolio.*, exposure.*, limits.*, stress.*"
        ),
    )

    # ── Snapshot ───────────────────────────────────────────────────────────────
    portfolio_snapshot_id: str = Field(
        description="SHA-256 del estado del portfolio usado para esta validación"
    )

    # ── Performance ───────────────────────────────────────────────────────────
    evaluation_time_ms: float = Field(ge=0, description="Tiempo de evaluación en milisegundos")
