"""
MessageRepository: persists agent messages to PostgreSQL.

Each save_* method writes to two tables atomically:
  1. messages.agent_messages  — append-only audit log (hypertable)
  2. trades.*                 — domain table for the specific message type

The pool argument must expose a `connection()` context manager
(compatible with shared_core.storage.postgres_pool.PostgresPool).
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

import psycopg2.extras

from multi_agent.communication.schemas import (
    AtlasValidationMessage,
    CritiqueMessage,
    DecisionMessage,
    ProposalMessage,
)

psycopg2.extras.register_uuid()

logger = logging.getLogger(__name__)


class MessageRepository:

    def __init__(self, pool) -> None:
        self._pool = pool

    # ── internal helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _to_json(msg) -> str:
        return json.dumps(msg.model_dump(mode="json"))

    @staticmethod
    def _insert_agent_message(cur, msg, channel: str) -> None:
        cur.execute(
            """
            INSERT INTO messages.agent_messages
                (message_id, message_type, correlation_id, agent_id, channel, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                msg.message_id,
                msg.message_type.value,
                msg.correlation_id,
                msg.agent_id.value.lower(),
                channel,
                MessageRepository._to_json(msg),
            ),
        )

    @staticmethod
    def _commit(conn, cur, *, rollback_on_error: bool = True) -> None:
        conn.commit()

    # ── public API ─────────────────────────────────────────────────────────────

    def save_proposal(
        self,
        msg: ProposalMessage,
        channel: str = "agent.proposals",
    ) -> None:
        with self._pool.connection() as conn:
            try:
                with conn.cursor() as cur:
                    self._insert_agent_message(cur, msg, channel)
                    cur.execute(
                        """
                        INSERT INTO trades.proposals
                            (correlation_id, proposing_agent, ticker, asset_class,
                             strategy_type, conviction_score, proposed_size_pct,
                             proposed_size_usd, full_payload)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            msg.correlation_id,
                            msg.agent_id.value.lower(),
                            msg.trade.ticker,
                            msg.trade.asset_class.value,
                            msg.trade.strategy_type.value,
                            msg.conviction_score,
                            float(msg.sizing.proposed_size_pct_portfolio),
                            float(msg.sizing.proposed_size_usd),
                            self._to_json(msg),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        logger.info("Saved proposal %s (corr=%s)", msg.message_id, msg.correlation_id)

    def save_critique(
        self,
        msg: CritiqueMessage,
        channel: str = "agent.critiques",
    ) -> None:
        with self._pool.connection() as conn:
            try:
                with conn.cursor() as cur:
                    self._insert_agent_message(cur, msg, channel)
                    cur.execute(
                        """
                        INSERT INTO trades.critiques
                            (correlation_id, critique_agent, stance,
                             contrarian_flag, summary, full_payload)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            msg.correlation_id,
                            msg.agent_id.value.lower(),
                            msg.stance.value,
                            msg.contrarian_flag_raised,
                            msg.argument.summary,
                            self._to_json(msg),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        logger.info(
            "Saved critique %s from %s (stance=%s)",
            msg.message_id,
            msg.agent_id,
            msg.stance,
        )

    def save_decision(
        self,
        msg: DecisionMessage,
        channel: str = "agent.decisions",
    ) -> None:
        with self._pool.connection() as conn:
            try:
                with conn.cursor() as cur:
                    self._insert_agent_message(cur, msg, channel)
                    cur.execute(
                        """
                        INSERT INTO trades.decisions
                            (correlation_id, outcome, consensus_type,
                             approved_size_pct, full_payload)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            msg.correlation_id,
                            msg.outcome.value,
                            msg.consensus_state.consensus_type.value,
                            msg.size_modulation.approved_size_pct
                            if msg.size_modulation
                            else None,
                            self._to_json(msg),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        logger.info("Saved decision %s (outcome=%s)", msg.message_id, msg.outcome)

    def save_atlas_validation(
        self,
        msg: AtlasValidationMessage,
        channel: str = "agent.atlas_validations",
    ) -> None:
        with self._pool.connection() as conn:
            try:
                with conn.cursor() as cur:
                    self._insert_agent_message(cur, msg, channel)
                    cur.execute(
                        """
                        INSERT INTO trades.atlas_validations
                            (correlation_id, atlas_decision, risk_mode,
                             buying_power_used_pct, full_payload)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            msg.correlation_id,
                            msg.decision.value,
                            msg.risk_mode.value,
                            msg.portfolio_impact.current_state.buying_power_used_pct,
                            self._to_json(msg),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        logger.info(
            "Saved atlas_validation %s (decision=%s)",
            msg.message_id,
            msg.decision,
        )

    def log_llm_cost(
        self,
        *,
        agent_id: str,
        task_type: str,
        model_used: str,
        input_tokens: int,
        cached_input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        criticality: str = "standard",
        correlation_id: UUID | None = None,
        is_batch_api: bool = False,
    ) -> None:
        with self._pool.connection() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO analytics.llm_costs
                            (agent_id, task_type, model_used, input_tokens,
                             cached_input_tokens, output_tokens, cost_usd,
                             is_batch_api, criticality, correlation_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            agent_id,
                            task_type,
                            model_used,
                            input_tokens,
                            cached_input_tokens,
                            output_tokens,
                            cost_usd,
                            is_batch_api,
                            criticality,
                            correlation_id,
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
