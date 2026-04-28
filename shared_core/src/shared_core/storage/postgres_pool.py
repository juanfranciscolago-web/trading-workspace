"""
PostgreSQL connection pool — shared between Eolo and multi-agent.

Wraps psycopg2's ThreadedConnectionPool with sane defaults for the trading
system's workload (mostly read-heavy with periodic writes).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)


class PostgresPool:
    """
    Wrapper around psycopg2 ThreadedConnectionPool.

    Designed to be used as a singleton across the application.
    """

    def __init__(
        self,
        dsn: str,
        min_connections: int = 2,
        max_connections: int = 10,
    ):
        # Lazy import to avoid hard dependency at module load
        try:
            from psycopg2.pool import ThreadedConnectionPool
        except ImportError:
            raise RuntimeError(
                "psycopg2 not installed. Run: pip install psycopg2-binary"
            )

        self._pool = ThreadedConnectionPool(
            min_connections,
            max_connections,
            dsn,
        )
        self.dsn = dsn
        logger.info(f"PostgresPool initialized: min={min_connections} max={max_connections}")

    @classmethod
    def from_env(cls) -> PostgresPool:
        """Initialize from DATABASE_URL environment variable."""
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL not set. Format: "
                "postgresql://user:pass@host:5432/dbname"
            )
        return cls(
            dsn=dsn,
            min_connections=int(os.environ.get("DB_POOL_MIN", "2")),
            max_connections=int(os.environ.get("DB_POOL_MAX", "10")),
        )

    def getconn(self):
        """Get a connection from the pool. Caller must return it."""
        return self._pool.getconn()

    def putconn(self, conn) -> None:
        """Return a connection to the pool."""
        self._pool.putconn(conn)

    @contextmanager
    def connection(self) -> Iterator:
        """Context manager that handles getconn/putconn automatically."""
        conn = self.getconn()
        try:
            yield conn
        finally:
            self.putconn(conn)

    @contextmanager
    def cursor(self) -> Iterator:
        """Context manager that yields a cursor with auto-commit on success."""
        with self.connection() as conn:
            try:
                with conn.cursor() as cur:
                    yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def close_all(self) -> None:
        """Close all connections (for shutdown)."""
        self._pool.closeall()
        logger.info("PostgresPool closed")


# =============================================================================
# Singleton
# =============================================================================

_global_pool: PostgresPool | None = None


def get_pool() -> PostgresPool:
    """Get or initialize the global pool."""
    global _global_pool
    if _global_pool is None:
        _global_pool = PostgresPool.from_env()
    return _global_pool


def reset_pool() -> None:
    """Reset singleton (for testing)."""
    global _global_pool
    if _global_pool is not None:
        _global_pool.close_all()
    _global_pool = None
