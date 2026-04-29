#!/usr/bin/env bash
# Run the multi-agent trading API in development mode.
# Binds to 127.0.0.1 only — not exposed to network (no auth in Sprint 2).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

export DATABASE_URL="${DATABASE_URL:-postgresql://trader:trader@localhost:5432/trading}"
export ATLAS_CONFIG_DIR="${ATLAS_CONFIG_DIR:-$PROJECT_DIR/config}"

exec uvicorn multi_agent.api.app:create_app \
    --factory \
    --host 127.0.0.1 \
    --port "${PORT:-8000}" \
    --reload \
    --log-level info
