"""
Fixtures for PostgreSQL integration tests.

Requires a running TimescaleDB instance (docker-compose up -d postgres).
All tests in this module are skipped automatically if the DB is unreachable.

Test database: trading_test (created fresh per session, dropped on teardown).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make db/ importable as top-level (migrate, reset_dev)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "db"))

_TEST_DB = "trading_test"


def _base_url() -> str:
    """Return the base URL without the database name."""
    url = os.environ.get("DATABASE_URL", "postgresql://trader:trader@localhost:5432/trading")
    return url.rsplit("/", 1)[0]


def _admin_dsn() -> str:
    return _base_url() + "/trading"


def _test_dsn() -> str:
    return _base_url() + f"/{_TEST_DB}"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: requires a running TimescaleDB instance",
    )


@pytest.fixture(scope="session")
def pg_available() -> bool:
    """True if the trading database is reachable."""
    try:
        import psycopg
        conn = psycopg.connect(_admin_dsn(), connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def test_db(pg_available):
    """
    Create trading_test, apply all migrations, yield the DSN, drop on teardown.
    Skips the whole session if PostgreSQL is unreachable.
    """
    if not pg_available:
        pytest.skip("PostgreSQL not available — skipping DB integration tests")

    import psycopg

    admin = _admin_dsn()
    test_dsn = _test_dsn()

    # CREATE DATABASE / DROP DATABASE must run outside a transaction block.
    # psycopg3: pass autocommit=True at connect time (cannot be changed mid-transaction).
    conn = psycopg.connect(admin, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{_TEST_DB}' AND pid <> pg_backend_pid()"
        )
        cur.execute(f"DROP DATABASE IF EXISTS {_TEST_DB}")
        cur.execute(f"CREATE DATABASE {_TEST_DB}")
    conn.close()

    # Apply all migrations
    from migrate import run as migrate_run
    migrate_run(dsn=test_dsn)

    yield test_dsn

    # Teardown
    conn = psycopg.connect(admin, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{_TEST_DB}' AND pid <> pg_backend_pid()"
        )
        cur.execute(f"DROP DATABASE IF EXISTS {_TEST_DB}")
    conn.close()


@pytest.fixture(scope="session")
def db_conn(test_db):
    """Persistent psycopg3 connection to trading_test for the whole test session."""
    import psycopg
    conn = psycopg.connect(test_db)
    yield conn
    conn.close()


@pytest.fixture
def cur(db_conn):
    """Per-test cursor; rolls back after each test to keep state clean."""
    with db_conn.cursor() as c:
        yield c
    db_conn.rollback()
