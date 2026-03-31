#!/usr/bin/env bash
set -euo pipefail

echo "[entrypoint] Waiting for Postgres ($APP_ENV)..."
until python -c "
from services.config import DATABASE_URL
import psycopg2
psycopg2.connect(DATABASE_URL)
" 2>/dev/null; do
  sleep 1
done

echo "[entrypoint] Starting server on port ${DASHBOARD_PORT:-7654}..."
exec uvicorn services.dashboard.app:app \
  --host 0.0.0.0 \
  --port "${DASHBOARD_PORT:-7654}"
