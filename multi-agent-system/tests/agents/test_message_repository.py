"""
Integration tests for MessageRepository.

Requires a running TimescaleDB instance and DATABASE_URL set.
Skipped automatically if the DB is unreachable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "db"))


def _dsn() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://trader:trader@localhost:5432/trading")


@pytest.fixture(scope="module")
def pool():
    try:
        import psycopg
        conn = psycopg.connect(_dsn(), connect_timeout=3)
        conn.close()
    except Exception:
        pytest.skip("PostgreSQL not available — skipping MessageRepository integration tests")

    # Use shared_core pool directly
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "shared_core" / "src"))
    from shared_core.storage.postgres_pool import PostgresPool
    p = PostgresPool(dsn=_dsn())
    yield p
    p.close_all()


@pytest.fixture
def repo(pool):
    from multi_agent.persistence import MessageRepository
    return MessageRepository(pool)


@pytest.fixture
def scenario_and_result():
    import random
    from multi_agent.agents import SCENARIOS, build_orchestrator

    class NullRepo:
        def save_proposal(self, m, **_): pass
        def save_critique(self, m, **_): pass
        def save_decision(self, m, **_): pass
        def save_atlas_validation(self, m, **_): pass
        def log_llm_cost(self, **_): pass

    orc = build_orchestrator(NullRepo())
    scenario = SCENARIOS["nyx_dissents"]
    result = orc.run_cycle(scenario)
    return scenario, result


class TestRepositorySavesProposal:
    def test_save_proposal_inserts_agent_message(self, repo, scenario_and_result, pool):
        _, result = scenario_and_result
        repo.save_proposal(result.proposal)

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT message_type, agent_id FROM messages.agent_messages "
                    "WHERE message_id = %s",
                    (result.proposal.message_id,),
                )
                row = cur.fetchone()
            conn.rollback()

        assert row is not None
        assert row[0] == "PROPOSAL"
        assert row[1] == "athena"

    def test_save_proposal_inserts_trade_proposal(self, repo, scenario_and_result, pool):
        _, result = scenario_and_result
        repo.save_proposal(result.proposal)

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT proposing_agent, ticker, conviction_score "
                    "FROM trades.proposals WHERE correlation_id = %s",
                    (result.proposal.correlation_id,),
                )
                row = cur.fetchone()
            conn.rollback()

        assert row is not None
        assert row[0] == "athena"
        assert row[1] == result.proposal.trade.ticker
        assert row[2] == result.proposal.conviction_score


class TestRepositorySavesCritique:
    def test_save_critique_inserts_both_tables(self, repo, scenario_and_result, pool):
        _, result = scenario_and_result
        nyx_critique = next(c for c in result.critiques if c.agent_id.value == "NYX")
        repo.save_critique(nyx_critique)

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT stance, contrarian_flag FROM trades.critiques "
                    "WHERE correlation_id = %s AND critique_agent = 'nyx'",
                    (nyx_critique.correlation_id,),
                )
                row = cur.fetchone()
            conn.rollback()

        assert row is not None
        assert row[0] == "DISAGREE"
        assert row[1] is True


class TestRepositorySavesDecision:
    def test_save_decision_inserts_both_tables(self, repo, scenario_and_result, pool):
        _, result = scenario_and_result
        repo.save_decision(result.decision)

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT outcome, consensus_type FROM trades.decisions "
                    "WHERE correlation_id = %s",
                    (result.decision.correlation_id,),
                )
                row = cur.fetchone()
            conn.rollback()

        assert row is not None
        assert row[0] == "APPROVED_WITH_CONDITIONS"


class TestRepositoryLogLlmCost:
    def test_log_llm_cost_inserts_row(self, repo, scenario_and_result, pool):
        _, result = scenario_and_result
        repo.log_llm_cost(
            agent_id="athena",
            task_type="proposal_generation",
            model_used="claude-sonnet-4-6",
            input_tokens=1500,
            cached_input_tokens=1200,
            output_tokens=300,
            cost_usd=0.00035,
            criticality="high",
            correlation_id=result.proposal.correlation_id,
        )

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cached_input_tokens, criticality FROM analytics.llm_costs "
                    "WHERE agent_id = 'athena' AND task_type = 'proposal_generation' "
                    "ORDER BY ts DESC LIMIT 1"
                )
                row = cur.fetchone()
            conn.rollback()

        assert row is not None
        assert row[0] == 1200
        assert row[1] == "high"


class TestRepositoryListProposals:

    def test_list_returns_saved_proposal(self, repo, scenario_and_result):
        """Default list (no filter) returns the just-saved proposal."""
        _, result = scenario_and_result
        repo.save_proposal(result.proposal)
        rows = repo.list_proposals(limit=100)
        saved_corr = str(result.proposal.correlation_id)
        assert any(str(r["correlation_id"]) == saved_corr for r in rows)

    def test_list_filter_by_agent_id(self, repo, scenario_and_result):
        """Filter by agent_id returns only rows from that agent."""
        _, result = scenario_and_result
        repo.save_proposal(result.proposal)
        agent_id = result.proposal.agent_id.value.lower()
        rows = repo.list_proposals(agent_id=agent_id, limit=100)
        assert rows  # at least the one we saved
        assert all(r["proposing_agent"] == agent_id for r in rows)

    def test_list_respects_limit(self, repo, scenario_and_result):
        """limit=1 returns exactly 1 row (we just inserted at least one)."""
        _, result = scenario_and_result
        repo.save_proposal(result.proposal)
        rows = repo.list_proposals(limit=1)
        assert len(rows) == 1

    def test_list_filter_by_days_recent(self, repo, scenario_and_result):
        """A just-saved proposal is within the days=1 window."""
        _, result = scenario_and_result
        repo.save_proposal(result.proposal)
        rows = repo.list_proposals(days=1, limit=100)
        saved_corr = str(result.proposal.correlation_id)
        assert any(str(r["correlation_id"]) == saved_corr for r in rows)


class TestRepositoryGetProposalByCorrelationId:

    def test_get_returns_saved_proposal(self, repo, scenario_and_result):
        """get_proposal_by_correlation_id finds the just-saved proposal."""
        _, result = scenario_and_result
        repo.save_proposal(result.proposal)
        row = repo.get_proposal_by_correlation_id(result.proposal.correlation_id)
        assert row is not None
        assert str(row["correlation_id"]) == str(result.proposal.correlation_id)
        assert "full_payload" in row

    def test_get_returns_none_for_unknown(self, repo):
        """Random unknown UUID returns None (not exception)."""
        from uuid import uuid4
        row = repo.get_proposal_by_correlation_id(uuid4())
        assert row is None

    def test_get_full_payload_roundtrips_to_proposal_message(self, repo, scenario_and_result):
        """save → get → ProposalMessage.model_validate (symmetric to _to_json)."""
        from multi_agent.communication.schemas import ProposalMessage
        _, result = scenario_and_result
        repo.save_proposal(result.proposal)
        row = repo.get_proposal_by_correlation_id(result.proposal.correlation_id)
        rebuilt = ProposalMessage.model_validate(row["full_payload"])
        assert rebuilt.correlation_id == result.proposal.correlation_id
        assert rebuilt.trade.ticker == result.proposal.trade.ticker
        assert rebuilt.conviction_score == result.proposal.conviction_score
