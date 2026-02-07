#!/bin/bash
set -e
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"

echo "==> Running backend tests..."
cd core && $PYTHON -m pytest tests/ -v -x "$@"
cd ..

echo ""
echo "==> Running frontend tests..."
cd bundled_agents/canvas/web && npx vitest run

echo ""
echo "==> All tests passed!"
