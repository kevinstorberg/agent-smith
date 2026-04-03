#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose exec app python -m pytest evals/test_suite.py -v "$@"
