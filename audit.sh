#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== Backend lint ==="
.venv/bin/ruff check .

echo ""
echo "=== Backend tests ==="
docker compose run --rm --build test "$@"

echo ""
echo "=== Frontend install ==="
cd services/dashboard/ui
npm ci

echo ""
echo "=== Frontend lint ==="
npm run lint

echo ""
echo "=== Frontend tests ==="
npm test

echo ""
echo "=== Frontend build ==="
npm run build
