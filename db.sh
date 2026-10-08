#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec "${LAUNCH_PYTHON:-python3}" scripts/manage.py upgrade "$@"
