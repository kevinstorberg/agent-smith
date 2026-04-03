#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

BUILD_ARGS=()
if [[ "${1:-}" == "-nc" ]]; then
  BUILD_ARGS+=(--no-cache --pull)
  shift
fi

echo "=== Stopping old containers ==="
docker compose down

echo ""
echo "=== Building app ==="
DOCKER_BUILDKIT=1 BUILDKIT_PROGRESS=plain docker compose build ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"} 2>&1 | cat

echo ""
echo "=== Generating ERD ==="
docker compose run --rm --entrypoint bash app -c \
  "python scripts/install_graphviz.py && python scripts/generate_erd.py -o ${HOME}/sondermind/agent-smith/docs/erd.png" \
  2>&1 | cat || echo "  ERD generation failed (non-fatal)"

echo ""
echo "=== Starting app ==="
docker compose up "$@" 2>&1 | cat
