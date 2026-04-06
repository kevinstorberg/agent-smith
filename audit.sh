#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "=== Backend lint ==="
docker compose run --rm --build lint

echo ""
echo "=== Backend tests ==="
docker compose --profile test down --volumes --remove-orphans
docker compose run --rm --build test "$@"

echo ""
echo "=== Frontend lint ==="
docker compose run --rm --build frontend npm run lint

echo ""
echo "=== Frontend tests ==="
docker compose run --rm frontend npm test

echo ""
echo "=== Frontend build ==="
docker compose run --rm frontend npm run build
