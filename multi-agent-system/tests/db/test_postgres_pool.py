"""
Unit tests for shared_core.storage.postgres_pool and trade_logger.

No real database required — uses MagicMock to simulate psycopg2.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest


# ── PostgresPool ──────────────────────────────────────────────────────────────

class TestPostgresPool:

    def _make_pool(self, mock_pool_cls):
        from shared_core.storage.postgres_pool import PostgresPool
        return PostgresPool.__new__(PostgresPool)

    def test_cursor_commits_on_success(self):
        from shared_core.storage.postgres_pool import PostgresPool

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        pool = MagicMock(spec=PostgresPool)
        pool.getconn.return_value = mock_conn
        pool.putconn = MagicMock()

        # Simulate what the real pool.connection() CM does
        from contextlib import contextmanager

        @contextmanager
        def fake_connection():
            yield mock_conn
            pool.putconn(mock_conn)

        pool.connection = fake_connection

        # Use the real cursor() CM logic
        real_pool = PostgresPool.__new__(PostgresPool)
        real_pool._pool = MagicMock()
        real_pool._pool.getconn.return_value = mock_conn
        real_pool._pool.putconn = pool.putconn

        with real_pool.cursor() as cur:
            pass  # success

        mock_conn.commit.assert_called_once()
        mock_conn.rollback.assert_not_called()

    def test_cursor_rolls_back_on_exception(self):
        from shared_core.storage.postgres_pool import PostgresPool

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cursor
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        real_pool = PostgresPool.__new__(PostgresPool)
        real_pool._pool = MagicMock()
        real_pool._pool.getconn.return_value = mock_conn

        with pytest.raises(ValueError):
            with real_pool.cursor():
                raise ValueError("boom")

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    def test_cursor_returns_connection_to_pool(self):
        """Verify putconn is called after cursor context exits."""
        from shared_core.storage.postgres_pool import PostgresPool

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda s: MagicMock()
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

        real_pool = PostgresPool.__new__(PostgresPool)
        real_pool._pool = MagicMock()
        real_pool._pool.getconn.return_value = mock_conn

        with real_pool.cursor():
            pass

        real_pool._pool.putconn.assert_called_once_with(mock_conn)

    def test_get_pool_returns_singleton(self):
        from shared_core.storage import postgres_pool

        postgres_pool.reset_pool()
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://x:x@localhost/x"}):
            with patch("psycopg2.pool.ThreadedConnectionPool"):
                pool1 = postgres_pool.get_pool()
                pool2 = postgres_pool.get_pool()
        assert pool1 is pool2
        postgres_pool.reset_pool()

    def test_reset_pool_clears_singleton(self):
        from shared_core.storage import postgres_pool

        postgres_pool.reset_pool()
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://x:x@localhost/x"}):
            with patch("psycopg2.pool.ThreadedConnectionPool"):
                pool1 = postgres_pool.get_pool()
        postgres_pool.reset_pool()
        assert postgres_pool._global_pool is None

    def test_from_env_raises_without_database_url(self):
        from shared_core.storage.postgres_pool import PostgresPool
        import os

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("DATABASE_URL", None)
            with pytest.raises(RuntimeError, match="DATABASE_URL not set"):
                PostgresPool.from_env()


# ── TradeLogger ───────────────────────────────────────────────────────────────

class TestTradeLogger:

    def _make_logger_with_mock_conn(self):
        """Return (TradeLogger, mock_conn, mock_cursor)."""
        from contextlib import contextmanager
        from shared_core.storage.trade_logger import TradeLogger

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (42,)
        mock_cursor.__enter__ = lambda s: mock_cursor
        mock_cursor.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        @contextmanager
        def fake_factory():
            yield mock_conn

        logger = TradeLogger(connection_factory=fake_factory)
        return logger, mock_conn, mock_cursor

    def test_cursor_commits_on_success(self):
        logger, mock_conn, _ = self._make_logger_with_mock_conn()
        with logger._cursor():
            pass
        mock_conn.commit.assert_called_once()
        mock_conn.rollback.assert_not_called()

    def test_cursor_rolls_back_on_exception(self):
        logger, mock_conn, _ = self._make_logger_with_mock_conn()
        with pytest.raises(RuntimeError):
            with logger._cursor():
                raise RuntimeError("db error")
        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    def test_connection_factory_called_per_operation(self):
        """connection_factory (pool.connection) must be called once per _cursor() use."""
        from contextlib import contextmanager
        from shared_core.storage.trade_logger import TradeLogger

        call_count = [0]

        @contextmanager
        def counting_factory():
            call_count[0] += 1
            conn = MagicMock()
            cursor = MagicMock()
            cursor.__enter__ = lambda s: cursor
            cursor.__exit__ = MagicMock(return_value=False)
            cursor.fetchone.return_value = (1,)
            conn.cursor.return_value = cursor
            yield conn

        logger = TradeLogger(connection_factory=counting_factory)
        with logger._cursor():
            pass
        with logger._cursor():
            pass
        assert call_count[0] == 2
