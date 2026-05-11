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

    def test_save_critique_full_payload_roundtrips(self, repo, pool):
        """save_critique → SELECT full_payload → CritiqueMessage.model_validate roundtrips
        all fields, including those without dedicated columns (veto_request,
        alternative_proposal, full argument body)."""
        from uuid import uuid4
        from multi_agent.communication.schemas import (
            CritiqueArgument,
            CritiqueMessage,
            EvidenceItem,
        )
        from multi_agent.communication.enums import AgentId, Stance

        original = CritiqueMessage(
            correlation_id=uuid4(),
            agent_id=AgentId.NYX,
            stance=Stance.DISAGREE,
            argument=CritiqueArgument(
                summary="Narrative-reality gap narrower than thesis claims",
                evidence=[
                    EvidenceItem(claim="Put/call skew flat", data_source="cboe", value=0.92),
                    EvidenceItem(claim="Insider buying minimal", data_source="form4_filings", value=3),
                    EvidenceItem(claim="Sentiment z-score", data_source="aaii", value="-0.4"),
                ],
                concern="Crowded short positioning may already be priced in",
                data_that_would_change_my_mind="Sustained put/call skew > 1.2 for 5 sessions",
            ),
            alternative_proposal={"strategy": "wait_for_confirmation", "delta_target": -0.20},
            veto_request=True,
            contrarian_flag_raised=True,
        )

        repo.save_critique(original)

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT full_payload FROM trades.critiques "
                    "WHERE correlation_id = %s AND critique_agent = 'nyx'",
                    (original.correlation_id,),
                )
                row = cur.fetchone()
            conn.rollback()

        assert row is not None
        rebuilt = CritiqueMessage.model_validate(row[0])

        # Whole-object equality (Pydantic v2 compares fields on frozen models).
        assert rebuilt == original

        # Explicit asserts on fields previously without column coverage —
        # clearer failure messages if any of these ever drop from full_payload.
        assert rebuilt.veto_request is True
        assert rebuilt.alternative_proposal == {
            "strategy": "wait_for_confirmation",
            "delta_target": -0.20,
        }
        assert rebuilt.argument.concern == original.argument.concern
        assert rebuilt.argument.data_that_would_change_my_mind == \
            original.argument.data_that_would_change_my_mind
        assert len(rebuilt.argument.evidence) == 3
        assert rebuilt.argument.evidence[0].data_source == "cboe"


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

    def test_save_decision_full_payload_roundtrips(self, repo, pool):
        """save_decision → SELECT full_payload → DecisionMessage.model_validate roundtrips
        all fields, including consensus_state membership, size_modulation, conditions,
        and atlas_validation (none of which have dedicated columns beyond approved_size_pct)."""
        from uuid import uuid4
        from multi_agent.communication.schemas import (
            AtlasValidationRef,
            ConsensusState,
            DecisionMessage,
            SizeModulation,
        )
        from multi_agent.communication.enums import (
            AgentId,
            ConsensusType,
            DecisionOutcome,
        )

        original = DecisionMessage(
            correlation_id=uuid4(),
            agent_id=AgentId.ATHENA,
            outcome=DecisionOutcome.APPROVED_WITH_CONDITIONS,
            consensus_state=ConsensusState(
                agree=[AgentId.ATHENA, AgentId.APOLLO, AgentId.HERMES],
                disagree=[AgentId.NYX],
                neutral=[AgentId.VESTA],
                consensus_type=ConsensusType.MAJORITY_WITH_PRODUCTIVE_DISAGREEMENT,
            ),
            size_modulation=SizeModulation(
                original_size_pct=2.0,
                approved_size_pct=1.2,
                reduction_reason="NYX dissent + ATLAS beta-bucket near limit",
            ),
            conditions=[
                "entry_only_above_vwap",
                "stop_at_thesis_invalidation",
                "exit_if_iv_collapses_below_25",
            ],
            atlas_validation=AtlasValidationRef(status="APPROVED"),
        )

        repo.save_decision(original)

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT full_payload FROM trades.decisions "
                    "WHERE correlation_id = %s",
                    (original.correlation_id,),
                )
                row = cur.fetchone()
            conn.rollback()

        assert row is not None
        rebuilt = DecisionMessage.model_validate(row[0])

        # Whole-object equality (Pydantic v2 compares fields on frozen models).
        assert rebuilt == original

        # Explicit asserts on fields previously without column coverage.
        assert rebuilt.conditions == [
            "entry_only_above_vwap",
            "stop_at_thesis_invalidation",
            "exit_if_iv_collapses_below_25",
        ]
        assert rebuilt.atlas_validation.status == "APPROVED"
        assert rebuilt.size_modulation is not None
        assert rebuilt.size_modulation.original_size_pct == 2.0
        assert rebuilt.size_modulation.reduction_reason == \
            "NYX dissent + ATLAS beta-bucket near limit"
        assert rebuilt.consensus_state.agree == [
            AgentId.ATHENA, AgentId.APOLLO, AgentId.HERMES,
        ]
        assert rebuilt.consensus_state.disagree == [AgentId.NYX]
        assert rebuilt.consensus_state.neutral == [AgentId.VESTA]


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
