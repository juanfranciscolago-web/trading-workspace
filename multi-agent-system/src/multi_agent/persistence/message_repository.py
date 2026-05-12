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
import json as _json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from multi_agent.communication.schemas import (
    AtlasValidationMessage,
    CritiqueMessage,
    DecisionMessage,
    ProposalMessage,
)

logger = logging.getLogger(__name__)


def _coerce_uuid(value) -> str:
    """Accept str or UUID; return str for psycopg3."""
    if isinstance(value, UUID):
        return str(value)
    return str(value)


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
                             proposed_size_usd, time_horizon_days, full_payload)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                            msg.thesis.time_horizon_days,
                            self._to_json(msg),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        logger.info("Saved proposal %s (corr=%s)", msg.message_id, msg.correlation_id)

    def update_proposal_status(
        self,
        correlation_id,
        status: str,
    ) -> None:
        """
        Update trades.proposals.status for a given correlation_id.

        Used by the worker chain (Sprint 4 B.4.5) to advance the proposal
        through its lifecycle: pending → under_critique → decided →
        atlas_validated (or rejected). The DB schema has status as a free
        VARCHAR (no Python enum); valid values are documented in the SQL
        schema comment for trades.proposals.status. Validation is the
        caller's responsibility — this method passes the status through
        to the DB without enum checks.

        Logs a warning if no row matched the correlation_id and continues
        silently (the proposal may have been deleted, never persisted, or
        this is a stale message from the bus DLQ).
        """
        with self._pool.connection() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE trades.proposals SET status = %s "
                        "WHERE correlation_id = %s",
                        (status, correlation_id),
                    )
                    rowcount = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        if rowcount == 0:
            logger.warning(
                "update_proposal_status: no proposal found for correlation_id=%s "
                "(status=%s); pipeline may proceed but proposal row is missing",
                correlation_id, status,
            )
        else:
            logger.info(
                "update_proposal_status: correlation_id=%s status=%s",
                correlation_id, status,
            )

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
        payload_json = self._to_json(msg)
        with self._pool.connection() as conn:
            try:
                with conn.cursor() as cur:
                    self._insert_agent_message(cur, msg, channel)
                    cur.execute(
                        """
                        INSERT INTO trades.atlas_validations
                            (correlation_id, atlas_decision, risk_mode,
                             full_payload,
                             approved, executed_size_pct, original_size_pct,
                             reason, atlas_version, portfolio_snapshot_id,
                             evaluation_time_ms, checks_passed, checks_failed,
                             metrics_snapshot)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            msg.correlation_id,
                            # deprecated columns — keep populated for backward compat
                            "APPROVED" if msg.approved else "BLOCKED",
                            msg.risk_mode.value,
                            payload_json,
                            # new columns
                            msg.approved,
                            float(msg.executed_size),
                            float(msg.original_size),
                            msg.reason,
                            msg.atlas_version,
                            msg.portfolio_snapshot_id,
                            msg.evaluation_time_ms,
                            msg.checks_passed or [],
                            msg.checks_failed or [],
                            _json.dumps(msg.metrics_snapshot),
                        ),
                    )
                    # Fix tech debt: update decision atlas_validated_at
                    cur.execute(
                        """
                        UPDATE trades.decisions
                           SET atlas_validated_at = %s
                         WHERE correlation_id = %s
                           AND atlas_validated_at IS NULL
                        """,
                        (datetime.now(timezone.utc), msg.correlation_id),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        logger.info(
            "Saved atlas_validation %s (approved=%s reason=%s)",
            msg.message_id,
            msg.approved,
            msg.reason,
        )

    def save_atlas_snapshot(
        self,
        snapshot_id: str,
        snapshot_at,
        nav_usd: float,
        cash_usd: float,
        buying_power_used_pct: float,
        portfolio_beta: float,
        vega_total: float,
        pnl_daily_usd: float,
        drawdown_from_peak_pct: float,
        positions: list,
    ) -> None:
        """Persist the portfolio snapshot used for an ATLAS validation."""
        with self._pool.connection() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO atlas.portfolio_snapshots
                            (snapshot_id, snapshot_at, nav_usd, cash_usd,
                             buying_power_used_pct, portfolio_beta, vega_total,
                             pnl_daily_usd, drawdown_from_peak_pct,
                             open_positions_count, positions_json)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (snapshot_id) DO NOTHING
                        """,
                        (
                            snapshot_id,
                            snapshot_at,
                            nav_usd,
                            cash_usd,
                            buying_power_used_pct,
                            portfolio_beta,
                            vega_total,
                            pnl_daily_usd,
                            drawdown_from_peak_pct,
                            len(positions),
                            _json.dumps(positions),
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def save_rejected_dlq(
        self,
        *,
        source: str,
        correlation_id,
        ticker: str | None,
        proposing_agent: str | None,
        reason: str,
        original_channel: str | None,
        dlq_entry_id: str | None,
        payload: dict,
        atlas_version: str | None = None,
    ) -> None:
        """Record a rejected or DLQ'd trade for human review."""
        with self._pool.connection() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO trades.rejected_dlq
                            (source, correlation_id, ticker, proposing_agent,
                             reason, original_channel, dlq_entry_id,
                             payload, atlas_version)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            source,
                            correlation_id,
                            ticker,
                            proposing_agent,
                            reason,
                            original_channel,
                            dlq_entry_id,
                            _json.dumps(payload),
                            atlas_version,
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        logger.info("Saved rejected_dlq (source=%s reason=%s)", source, reason)

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

    # ── read methods (Sprint 3 B.3.6) ─────────────────────────────────────────

    def list_proposals(
        self,
        days: int = 7,
        limit: int = 50,
        agent_id: str | None = None,
    ) -> list[dict]:
        """
        Return recent proposals from trades.proposals (extracted columns only).

        Filter by agent_id (case-insensitive: lowercased before WHERE) and by
        time window (created_at >= now - days). Ordered by created_at DESC.

        full_payload JSONB is intentionally excluded — use
        get_proposal_by_correlation_id for the full ProposalMessage payload.
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        with self._pool.cursor() as cur:
            if agent_id is None:
                cur.execute(
                    """
                    SELECT correlation_id, proposing_agent, ticker, asset_class,
                           strategy_type, conviction_score, proposed_size_pct,
                           proposed_size_usd, time_horizon_days, status, created_at
                    FROM trades.proposals
                    WHERE created_at >= %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (since, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT correlation_id, proposing_agent, ticker, asset_class,
                           strategy_type, conviction_score, proposed_size_pct,
                           proposed_size_usd, time_horizon_days, status, created_at
                    FROM trades.proposals
                    WHERE proposing_agent = %s
                      AND created_at >= %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (agent_id.lower(), since, limit),
                )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if rows else []
        return [dict(zip(cols, r)) for r in rows]

    def get_proposal_by_correlation_id(self, correlation_id) -> dict | None:
        """
        Return full proposal row (including full_payload JSONB) or None.

        Used by the detail endpoint to reconstruct the ProposalMessage via
        ProposalMessage.model_validate(row["full_payload"]).
        """
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT correlation_id, proposing_agent, ticker, asset_class,
                       strategy_type, conviction_score, proposed_size_pct,
                       proposed_size_usd, time_horizon_days, status,
                       full_payload, created_at
                FROM trades.proposals
                WHERE correlation_id = %s
                """,
                (_coerce_uuid(correlation_id),),
            )
            row = cur.fetchone()
            cols = [d[0] for d in cur.description] if row else []
        return dict(zip(cols, row)) if row else None

    def list_critiques_by_correlation_id(
        self,
        correlation_id,
    ) -> list[CritiqueMessage]:
        """
        Return all critiques for a correlation_id as validated
        CritiqueMessage instances, ordered chronologically (created_at ASC).

        Sprint 4: typically 0 or 1 critique (only APOLLO is a real critic).
        Future sprints: up to N as HERMES/NYX/VESTA come online. The list
        shape is future-proof; the schema's UNIQUE(correlation_id,
        critique_agent) constraint guarantees no duplicates from the same
        critic, but does not bound N.

        Unlike get_proposal_by_correlation_id (which returns a dict
        because the list endpoint also needs the extracted columns), this
        method returns the validated Pydantic model directly — the read
        endpoints for critiques always want the full message. Design
        divergence is deliberate (B.4.6 spec).
        """
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT full_payload FROM trades.critiques
                WHERE correlation_id = %s
                ORDER BY created_at ASC
                """,
                (_coerce_uuid(correlation_id),),
            )
            rows = cur.fetchall()
        return [CritiqueMessage.model_validate(row[0]) for row in rows]

    def get_decision_by_correlation_id(
        self,
        correlation_id,
    ) -> DecisionMessage | None:
        """
        Return the decision for a correlation_id as a validated
        DecisionMessage, or None if no decision exists yet (chain
        mid-flight) or the correlation_id is unknown.

        Schema guarantees at most 1 decision per correlation_id (UNIQUE
        constraint uq_decisions_correlation).
        """
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT full_payload FROM trades.decisions
                WHERE correlation_id = %s
                """,
                (_coerce_uuid(correlation_id),),
            )
            row = cur.fetchone()
        return DecisionMessage.model_validate(row[0]) if row else None

    def get_atlas_validation_by_correlation_id(
        self,
        correlation_id,
    ) -> AtlasValidationMessage | None:
        """
        Return the ATLAS validation for a correlation_id as a validated
        AtlasValidationMessage, or None if validation has not produced yet
        or the correlation_id is unknown.

        Schema guarantees at most 1 validation per correlation_id (UNIQUE
        constraint uq_atlas_validations_correlation).
        """
        with self._pool.cursor() as cur:
            cur.execute(
                """
                SELECT full_payload FROM trades.atlas_validations
                WHERE correlation_id = %s
                """,
                (_coerce_uuid(correlation_id),),
            )
            row = cur.fetchone()
        return AtlasValidationMessage.model_validate(row[0]) if row else None
