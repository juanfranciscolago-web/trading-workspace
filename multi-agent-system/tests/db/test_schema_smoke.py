"""
Integration smoke tests: INSERT/SELECT on every table, constraint checks,
and hypertable-specific behavior.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration

TS = datetime(2026, 4, 28, 14, 30, tzinfo=timezone.utc)
CORR = uuid4()


class TestShared:

    def test_insert_and_select_trades_log(self, cur):
        exec_id = str(uuid4())
        cur.execute("""
            INSERT INTO shared.trades_log
                (execution_id, source, symbol, asset_class, direction, quantity, status)
            VALUES (%s, 'multi_agent_athena', 'MSFT', 'option', 'sell', 10, 'filled')
        """, (exec_id,))
        cur.execute(
            "SELECT execution_id, source FROM shared.trades_log WHERE execution_id = %s",
            (exec_id,),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == exec_id
        assert row[1] == "multi_agent_athena"

    def test_invalid_source_rejected(self, cur):
        import psycopg2
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("""
                INSERT INTO shared.trades_log
                    (execution_id, source, symbol, asset_class, direction, quantity, status)
                VALUES (%s, 'invalid_source', 'AAPL', 'equity', 'buy', 100, 'filled')
            """, (str(uuid4()),))


class TestAgents:

    def test_select_agent_config(self, cur):
        cur.execute("SELECT agent_id, max_portfolio_pct FROM agents.config ORDER BY agent_id")
        rows = {row[0]: float(row[1]) for row in cur.fetchall()}
        assert "athena" in rows
        assert rows["atlas"] == 0.0
        assert rows["hermes"] == 10.0

    def test_update_agent_state(self, cur):
        cur.execute("""
            UPDATE agents.state SET status = 'analyzing', current_task = 'scanning MSFT options'
            WHERE agent_id = 'athena'
        """)
        cur.execute("SELECT status, current_task FROM agents.state WHERE agent_id = 'athena'")
        row = cur.fetchone()
        assert row[0] == "analyzing"
        assert row[1] == "scanning MSFT options"

    def test_state_fk_rejects_unknown_agent(self, cur):
        import psycopg2
        with pytest.raises(psycopg2.errors.ForeignKeyViolation):
            cur.execute(
                "INSERT INTO agents.state (agent_id) VALUES ('unknown_agent')"
            )


class TestMessages:

    def test_insert_agent_message(self, cur):
        msg_id = uuid4()
        cur.execute("""
            INSERT INTO messages.agent_messages
                (message_id, message_type, correlation_id, agent_id, channel, payload)
            VALUES (%s, 'PROPOSAL', %s, 'athena', 'agent.proposals', %s)
        """, (msg_id, CORR, json.dumps({"test": True})))
        cur.execute(
            "SELECT message_type, agent_id FROM messages.agent_messages WHERE message_id = %s",
            (msg_id,),
        )
        row = cur.fetchone()
        assert row[0] == "PROPOSAL"
        assert row[1] == "athena"

    def test_message_id_index_exists(self, cur):
        # TimescaleDB hypertables cannot have unique indexes without the partition column.
        # message_id uniqueness is enforced at the application level (uuid4 guarantees).
        # Verify the non-unique index exists for query performance.
        cur.execute("""
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'messages'
              AND tablename = 'agent_messages'
              AND indexname = 'idx_agent_messages_message_id'
        """)
        assert cur.fetchone() is not None


class TestTrades:

    def test_full_lifecycle_insert(self, cur):
        corr = uuid4()

        # Proposal
        cur.execute("""
            INSERT INTO trades.proposals
                (correlation_id, proposing_agent, ticker, asset_class,
                 strategy_type, conviction_score, full_payload)
            VALUES (%s, 'athena', 'MSFT', 'option', 'csp', 78, '{}')
        """, (corr,))

        # Critique
        cur.execute("""
            INSERT INTO trades.critiques
                (correlation_id, critique_agent, stance, full_payload)
            VALUES (%s, 'nyx', 'DISAGREE', '{}')
        """, (corr,))

        # Decision
        cur.execute("""
            INSERT INTO trades.decisions
                (correlation_id, outcome, full_payload)
            VALUES (%s, 'APPROVED_WITH_CONDITIONS', '{}')
        """, (corr,))

        # Atlas validation
        cur.execute("""
            INSERT INTO trades.atlas_validations
                (correlation_id, atlas_decision, risk_mode, full_payload)
            VALUES (%s, 'APPROVED', 'GREEN', '{}')
        """, (corr,))

        # Execution
        cur.execute("""
            INSERT INTO trades.executions
                (correlation_id, fill_status, fill_price, fill_quantity, full_payload)
            VALUES (%s, 'filled', 4.82, 10, '{}')
        """, (corr,))

        # Verify correlation_id links everything
        for table in ("proposals", "critiques", "decisions", "atlas_validations"):
            cur.execute(f"SELECT COUNT(*) FROM trades.{table} WHERE correlation_id = %s", (corr,))
            assert cur.fetchone()[0] == 1, f"Expected 1 row in trades.{table}"

    def test_conviction_score_constraint(self, cur):
        import psycopg2
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("""
                INSERT INTO trades.proposals
                    (correlation_id, proposing_agent, ticker, asset_class,
                     strategy_type, conviction_score, full_payload)
                VALUES (%s, 'athena', 'MSFT', 'option', 'csp', 150, '{}')
            """, (uuid4(),))

    def test_duplicate_critique_from_same_agent_rejected(self, cur):
        import psycopg2
        corr = uuid4()
        cur.execute("""
            INSERT INTO trades.critiques (correlation_id, critique_agent, stance, full_payload)
            VALUES (%s, 'nyx', 'DISAGREE', '{}')
        """, (corr,))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("""
                INSERT INTO trades.critiques (correlation_id, critique_agent, stance, full_payload)
                VALUES (%s, 'nyx', 'AGREE', '{}')
            """, (corr,))


class TestPortfolio:

    def test_insert_snapshot(self, cur):
        cur.execute("""
            INSERT INTO portfolio.snapshots
                (snapshot_at, total_nav_usd, risk_mode)
            VALUES (%s, 1000000.00, 'GREEN')
        """, (TS,))
        cur.execute(
            "SELECT total_nav_usd, risk_mode FROM portfolio.snapshots WHERE snapshot_at = %s",
            (TS,),
        )
        row = cur.fetchone()
        assert float(row[0]) == 1000000.0
        assert row[1] == "GREEN"

    def test_insert_open_position(self, cur):
        pos_id = str(uuid4())
        cur.execute("""
            INSERT INTO portfolio.positions
                (position_id, source, ticker, asset_class,
                 quantity, entry_price, entry_timestamp)
            VALUES (%s, 'multi_agent_athena', 'MSFT', 'option', -10, 4.85, %s)
        """, (pos_id, TS))
        cur.execute(
            "SELECT is_open, quantity FROM portfolio.positions WHERE position_id = %s",
            (pos_id,),
        )
        row = cur.fetchone()
        assert row[0] is True
        assert row[1] == -10


class TestMarket:

    def test_insert_ohlcv_bar(self, cur):
        cur.execute("""
            INSERT INTO market.ohlcv (ts, ticker, timeframe, open, high, low, close, volume)
            VALUES (%s, 'MSFT', '1d', 415.00, 418.50, 413.20, 416.75, 22000000)
        """, (TS,))
        cur.execute(
            "SELECT close, volume FROM market.ohlcv WHERE ts = %s AND ticker = 'MSFT'",
            (TS,),
        )
        row = cur.fetchone()
        assert float(row[0]) == 416.75
        assert row[1] == 22000000

    def test_insert_iv_surface_point(self, cur):
        cur.execute("""
            INSERT INTO market.iv_surface
                (ts, underlying, expiration, strike, option_type, iv)
            VALUES (%s, 'MSFT', '2026-06-19', 410.0, 'PUT', 0.2850)
        """, (TS,))
        cur.execute(
            "SELECT iv FROM market.iv_surface "
            "WHERE ts = %s AND underlying = 'MSFT' AND option_type = 'PUT'",
            (TS,),
        )
        row = cur.fetchone()
        assert abs(float(row[0]) - 0.285) < 1e-6


class TestAnalytics:

    def test_insert_risk_mode_transition(self, cur):
        cur.execute("""
            INSERT INTO analytics.risk_mode_transitions
                (from_mode, to_mode, duration_in_previous_mode_seconds, trigger_reason)
            VALUES ('GREEN', 'YELLOW', 3600, 'drawdown exceeded 10%')
        """)
        cur.execute(
            "SELECT from_mode, to_mode FROM analytics.risk_mode_transitions "
            "ORDER BY transitioned_at DESC LIMIT 1"
        )
        row = cur.fetchone()
        assert row[0] == "GREEN"
        assert row[1] == "YELLOW"

    def test_insert_trust_score(self, cur):
        cur.execute("""
            INSERT INTO analytics.agent_trust_scores
                (from_agent, to_agent, context, total_disagreements,
                 correct_disagreements, current_trust_score)
            VALUES ('nyx', 'athena', 'csp_setup', 5, 3, 0.6000)
        """)
        cur.execute(
            "SELECT current_trust_score FROM analytics.agent_trust_scores "
            "WHERE from_agent = 'nyx' AND to_agent = 'athena'"
        )
        row = cur.fetchone()
        assert abs(float(row[0]) - 0.6) < 1e-4

    def test_trust_score_unique_constraint(self, cur):
        import psycopg2
        cur.execute("""
            INSERT INTO analytics.agent_trust_scores
                (from_agent, to_agent, context, current_trust_score)
            VALUES ('apollo', 'nyx', 'macro_thesis', 0.5)
        """)
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("""
                INSERT INTO analytics.agent_trust_scores
                    (from_agent, to_agent, context, current_trust_score)
                VALUES ('apollo', 'nyx', 'macro_thesis', 0.7)
            """)

    def test_insert_llm_cost_with_cache_fields(self, cur):
        cur.execute("""
            INSERT INTO analytics.llm_costs
                (agent_id, task_type, model_used, input_tokens,
                 cached_input_tokens, output_tokens, cost_usd,
                 is_batch_api, criticality)
            VALUES ('athena', 'proposal_generation', 'claude-sonnet-4-6',
                    2000, 1800, 350, 0.000420, false, 'high')
        """)
        cur.execute(
            "SELECT cached_input_tokens, criticality FROM analytics.llm_costs "
            "WHERE agent_id = 'athena' ORDER BY ts DESC LIMIT 1"
        )
        row = cur.fetchone()
        assert row[0] == 1800
        assert row[1] == "high"
