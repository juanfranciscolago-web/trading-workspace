#!/usr/bin/env python3
"""
Apply pending SQL migrations to the trading database.

Usage:
    python db/migrate.py                    # uses DATABASE_URL env var
    python db/migrate.py postgresql://...   # explicit DSN as first argument

Migrations live in db/migrations/V*.sql (Flyway-style naming).
Each migration is recorded in schema_migrations with a SHA-256 checksum.
Editing an applied migration raises a RuntimeError — create a new version instead.

Safe to re-run: already-applied migrations are skipped.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _split_statements(sql: str) -> list[str]:
    """
    Split a SQL file into individual statements on ';' boundaries.
    Strips single-line comments first to avoid semicolons inside comments
    causing false splits (e.g. '-- foo; bar' must not split).
    """
    import re
    sql_no_comments = re.sub(r"--[^\n]*", "", sql)
    result = []
    for chunk in sql_no_comments.split(";"):
        stmt = chunk.strip()
        if stmt:
            result.append(stmt)
    return result


def _exec_statement(cur, stmt: str) -> None:
    """Execute one statement; consume any result set (e.g. SELECT create_hypertable)."""
    cur.execute(stmt)
    if cur.description:
        cur.fetchall()


def list_migrations() -> list[tuple[str, Path]]:
    """Return (version, path) pairs sorted by version string."""
    result = []
    for f in sorted(MIGRATIONS_DIR.glob("V*.sql")):
        m = re.match(r"^(V\d+)__", f.name)
        if m:
            result.append((m.group(1), f))
    return result


# ── Core ──────────────────────────────────────────────────────────────────────

def _ensure_migrations_table(conn) -> None:
    """Bootstrap schema_migrations table before applying V001 (which also creates it)."""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     VARCHAR(20)  PRIMARY KEY,
                filename    VARCHAR(200) NOT NULL,
                applied_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                checksum    VARCHAR(64)  NOT NULL
            )
        """)
    conn.commit()


def _get_applied(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT version, checksum FROM schema_migrations ORDER BY version")
        return {row[0]: row[1] for row in cur.fetchall()}


def run(dsn: str | None = None) -> int:
    """
    Apply all pending migrations.

    Args:
        dsn: PostgreSQL connection string. Falls back to DATABASE_URL env var.

    Returns:
        Number of migrations applied in this run.

    Raises:
        RuntimeError: DATABASE_URL not set, or checksum mismatch on applied migration.
        psycopg2.Error: Any database error during migration execution.
    """
    try:
        import psycopg2
    except ImportError:
        raise RuntimeError("psycopg2 not installed. Run: pip install psycopg2-binary")

    dsn = dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL not set.\n"
            "Format: postgresql://user:pass@host:5432/dbname"
        )

    migrations = list_migrations()
    if not migrations:
        logger.warning("No migration files found in %s", MIGRATIONS_DIR)
        print("  No migration files found.")
        return 0

    conn = psycopg2.connect(dsn)
    try:
        _ensure_migrations_table(conn)
        applied = _get_applied(conn)
        applied_count = 0

        for version, path in migrations:
            content = path.read_text(encoding="utf-8")
            checksum = _sha256(content)

            if version in applied:
                if applied[version] != checksum:
                    raise RuntimeError(
                        f"Checksum mismatch for {version} ({path.name}).\n"
                        f"  recorded : {applied[version][:16]}…\n"
                        f"  current  : {checksum[:16]}…\n"
                        "Never edit an applied migration — create a new version instead."
                    )
                logger.debug("%s already applied, skipping", version)
                continue

            print(f"  Applying {version}: {path.name} …", flush=True)
            try:
                with conn.cursor() as cur:
                    for stmt in _split_statements(content):
                        _exec_statement(cur, stmt)
                    cur.execute(
                        "INSERT INTO schema_migrations (version, filename, checksum) "
                        "VALUES (%s, %s, %s)",
                        (version, path.name, checksum),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

            applied_count += 1
            print(f"  ✓ {version} applied", flush=True)

        if applied_count == 0:
            print("  All migrations already applied. Nothing to do.")
        else:
            print(f"\n  {applied_count} migration(s) applied successfully.")

        return applied_count
    finally:
        conn.close()


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    explicit_dsn = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        run(dsn=explicit_dsn)
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
