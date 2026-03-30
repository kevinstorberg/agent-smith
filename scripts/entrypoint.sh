#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Waiting for Postgres..."
until python -c "
import psycopg2, os
psycopg2.connect(os.environ.get('DATABASE_URL', 'postgresql://localhost/agent_smith'))
" 2>/dev/null; do
  sleep 1
done

echo "[entrypoint] Starting server on port ${DASHBOARD_PORT:-7654}..."
exec uvicorn services.dashboard.app:app \
  --host 0.0.0.0 \
  --port "${DASHBOARD_PORT:-7654}"
