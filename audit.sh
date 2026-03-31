#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== Backend lint ==="
.venv/bin/ruff check .

echo ""
echo "=== Backend tests ==="
docker compose run --rm --build test "$@"

echo ""
echo "=== Frontend lint ==="
cd services/dashboard/ui
npm run lint

echo ""
echo "=== Frontend tests ==="
npm test

echo ""
echo "=== Frontend build ==="
npm run build
