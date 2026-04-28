#!/usr/bin/env bash
# Run all workspace tests. Each subproject is tested from its own directory
# to avoid path resolution conflicts with multi-agent-system/pyproject.toml.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

source "$ROOT/venv/bin/activate"

echo "=== shared_core ==="
pytest "$ROOT/shared_core/tests/" -q

echo "=== multi-agent-system ==="
(cd "$ROOT/multi-agent-system" && pytest tests/ -q)

echo "=== claude_router ==="
(cd "$ROOT/multi-agent-system/claude_router" && pytest tests/ -q)

echo ""
echo "✓ All subprojects passed."
