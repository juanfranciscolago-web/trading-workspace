"""
Integration tests: verify the DB schema is exactly what the migrations define.

Checks:
  - All expected schemas exist
  - All expected tables exist
  - Hypertables are registered in timescaledb_information
  - Critical indexes exist
  - schema_migrations records all 9 versions
  - agents.config is seeded with 6 rows
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

EXPECTED_SCHEMAS = {
    "shared", "agents", "messages", "trades",
    "portfolio", "market", "analytics",
}

EXPECTED_TABLES = {
    ("shared",    "trades_log"),
    ("agents",    "config"),
    ("agents",    "state"),
    ("messages",  "agent_messages"),
    ("trades",    "proposals"),
    ("trades",    "critiques"),
    ("trades",    "decisions"),
    ("trades",    "atlas_validations"),
    ("trades",    "executions"),
    ("trades",    "postmortems"),
    ("portfolio", "snapshots"),
    ("portfolio", "positions"),
    ("market",    "ohlcv"),
    ("market",    "iv_surface"),
    ("analytics", "agent_performance"),
    ("analytics", "calibration"),
    ("analytics", "llm_costs"),
    ("analytics", "risk_mode_transitions"),
    ("analytics", "agent_trust_scores"),
}

EXPECTED_HYPERTABLES = {
    ("messages",  "agent_messages"),
    ("trades",    "executions"),
    ("portfolio", "snapshots"),
    ("market",    "ohlcv"),
    ("market",    "iv_surface"),
    ("analytics", "agent_performance"),
    ("analytics", "llm_costs"),
}

EXPECTED_MIGRATION_VERSIONS = {
    "V001", "V002", "V003", "V004", "V005",
    "V006", "V007", "V008", "V009",
    "V010", "V011", "V012", "V013",
    "V014",
}

EXPECTED_AGENT_IDS = {"athena", "apollo", "hermes", "nyx", "vesta", "atlas"}


class TestSchemas:

    def test_all_schemas_exist(self, cur):
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name = ANY(%s)",
            (list(EXPECTED_SCHEMAS),),
        )
        found = {row[0] for row in cur.fetchall()}
        missing = EXPECTED_SCHEMAS - found
        assert not missing, f"Missing schemas: {missing}"


class TestTables:

    def test_all_tables_exist(self, cur):
        cur.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema = ANY(%s) AND table_type = 'BASE TABLE'",
            (list(EXPECTED_SCHEMAS),),
        )
        found = {(row[0], row[1]) for row in cur.fetchall()}
        missing = EXPECTED_TABLES - found
        assert not missing, f"Missing tables: {missing}"


class TestHypertables:

    def test_hypertables_registered_in_timescaledb(self, cur):
        cur.execute(
            "SELECT hypertable_schema, hypertable_name "
            "FROM timescaledb_information.hypertables"
        )
        found = {(row[0], row[1]) for row in cur.fetchall()}
        missing = EXPECTED_HYPERTABLES - found
        assert not missing, f"Tables not converted to hypertables: {missing}"

    def test_hypertable_chunk_intervals(self, cur):
        """Spot-check that time dimensions exist for key hypertables."""
        cur.execute("""
            SELECT h.hypertable_schema, h.hypertable_name,
                   d.time_interval
            FROM timescaledb_information.hypertables h
            JOIN timescaledb_information.dimensions d
                ON d.hypertable_schema = h.hypertable_schema
               AND d.hypertable_name = h.hypertable_name
            WHERE h.hypertable_schema IN ('market', 'messages')
              AND d.dimension_type = 'Time'
        """)
        results = {(row[0], row[1]): row[2] for row in cur.fetchall()}
        assert ("market", "ohlcv") in results, "market.ohlcv has no time dimension"
        assert ("market", "iv_surface") in results, "market.iv_surface has no time dimension"
        assert ("messages", "agent_messages") in results, "messages.agent_messages has no time dimension"
        # Verify intervals are non-null (actual value depends on TimescaleDB version repr)
        for key, interval in results.items():
            assert interval is not None, f"{key} has null time_interval"


class TestIndexes:

    def _index_exists(self, cur, schema: str, table: str, index: str) -> bool:
        cur.execute(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = %s AND tablename = %s AND indexname = %s",
            (schema, table, index),
        )
        return cur.fetchone() is not None

    def test_critical_indexes_exist(self, cur):
        critical = [
            ("shared",    "trades_log",    "idx_trades_log_fill_timestamp"),
            ("messages",  "agent_messages", "idx_agent_messages_correlation"),
            ("trades",    "proposals",     "idx_proposals_active_status"),
            ("trades",    "critiques",     "idx_critiques_correlation"),
            ("trades",    "executions",    "idx_executions_correlation"),
            ("market",    "ohlcv",         "idx_ohlcv_ticker_tf_time"),
            ("analytics", "risk_mode_transitions", "idx_risk_transitions_time"),
            ("analytics", "agent_trust_scores",    "idx_trust_lookup"),
        ]
        missing = [
            f"{schema}.{table}.{index}"
            for schema, table, index in critical
            if not self._index_exists(cur, schema, table, index)
        ]
        assert not missing, f"Missing indexes: {missing}"


class TestMigrationTracking:

    def test_all_versions_recorded(self, cur):
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        recorded = {row[0] for row in cur.fetchall()}
        missing = EXPECTED_MIGRATION_VERSIONS - recorded
        assert not missing, f"Migration versions not recorded: {missing}"

    def test_no_extra_versions(self, cur):
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        recorded = {row[0] for row in cur.fetchall()}
        extra = recorded - EXPECTED_MIGRATION_VERSIONS
        assert not extra, f"Unexpected migration versions in DB: {extra}"


class TestSeedData:

    def test_six_agents_in_config(self, cur):
        cur.execute("SELECT agent_id FROM agents.config ORDER BY agent_id")
        found = {row[0] for row in cur.fetchall()}
        assert found == EXPECTED_AGENT_IDS

    def test_agent_state_seeded_for_all_agents(self, cur):
        cur.execute("SELECT agent_id FROM agents.state ORDER BY agent_id")
        found = {row[0] for row in cur.fetchall()}
        assert found == EXPECTED_AGENT_IDS

    def test_atlas_has_zero_max_portfolio_pct(self, cur):
        cur.execute(
            "SELECT max_portfolio_pct FROM agents.config WHERE agent_id = 'atlas'"
        )
        row = cur.fetchone()
        assert row is not None
        assert float(row[0]) == 0.0

    def test_all_agents_default_to_idle(self, cur):
        cur.execute("SELECT status FROM agents.state WHERE status != 'idle'")
        non_idle = cur.fetchall()
        assert not non_idle, f"Some agents not in 'idle' state: {non_idle}"
