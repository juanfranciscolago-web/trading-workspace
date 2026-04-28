#!/usr/bin/env python3
"""
⚠️  DEV ONLY — drops all schemas and re-applies migrations from scratch.

Never run this against production or staging.
Requires DATABASE_URL to point to a local development database.

Usage:
    python db/reset_dev.py
    python db/reset_dev.py --confirm   # skip interactive prompt
"""
from __future__ import annotations

import os
import sys

PROTECTED_HOSTS = ("prod", "staging", "rds.amazonaws.com", "render.com")


def _check_dsn_is_safe(dsn: str) -> None:
    for fragment in PROTECTED_HOSTS:
        if fragment in dsn.lower():
            raise SystemExit(
                f"REFUSED: DSN contains '{fragment}' — "
                "reset_dev.py must never touch production."
            )


def main() -> None:
    try:
        import psycopg2
    except ImportError:
        raise SystemExit("psycopg2 not installed. Run: pip install psycopg2-binary")

    dsn = os.environ.get("DATABASE_URL", "postgresql://trader:trader@localhost:5432/trading")
    _check_dsn_is_safe(dsn)

    skip_prompt = "--confirm" in sys.argv
    if not skip_prompt:
        print(f"⚠️  This will DROP ALL SCHEMAS on:\n   {dsn}\n")
        answer = input("Type 'yes' to continue: ").strip().lower()
        if answer != "yes":
            print("Aborted.")
            return

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    schemas = ["analytics", "market", "portfolio", "trades", "messages", "agents", "shared"]
    try:
        with conn.cursor() as cur:
            for schema in schemas:
                print(f"  Dropping schema {schema} …")
                cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cur.execute("DROP TABLE IF EXISTS schema_migrations")
        print("  All schemas dropped.\n")
    finally:
        conn.close()

    print("  Re-applying migrations …\n")
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from migrate import run
    run(dsn=dsn)
    print("\n  Reset complete.")


if __name__ == "__main__":
    main()
