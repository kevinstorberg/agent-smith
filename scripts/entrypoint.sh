#!/usr/bin/env bash
set -euo pipefail

# Resolve the correct DATABASE_URL based on APP_ENV
DB_VAR="DATABASE_URL_${APP_ENV^^}"
DB_URL="${!DB_VAR:-}"

if [ -z "$DB_URL" ]; then
  echo "[entrypoint] ERROR: $DB_VAR is not set for APP_ENV=$APP_ENV"
  exit 1
fi

echo "[entrypoint] Waiting for Postgres ($APP_ENV)..."
until python -c "
import psycopg2
psycopg2.connect('$DB_URL')
" 2>/dev/null; do
  sleep 1
done

echo "[entrypoint] Starting server on port ${DASHBOARD_PORT:-7654}..."
exec uvicorn services.dashboard.app:app \
  --host 0.0.0.0 \
  --port "${DASHBOARD_PORT:-7654}"
