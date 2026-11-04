#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
for argument in "$@"; do
  case "$argument" in
    -h|--help|--status|--stop)
      exec "${LAUNCH_PYTHON:-python3}" scripts/manage.py run "$@"
      ;;
  esac
done

activation="${AGENT_SMITH_VENV_ACTIVATE:-$PWD/.venv/bin/activate}"
if [[ ! -f "$activation" || ! -r "$activation" ]]; then
  echo "Agent Smith: virtual environment activation is unavailable; run ./setup.sh or set AGENT_SMITH_VENV_ACTIVATE." >&2
  exit 1
fi
# The checked activation path is selected at runtime, so static lookup cannot resolve it.
# shellcheck disable=SC1090
source "$activation"
export AGENT_SMITH_PYTHON="${AGENT_SMITH_PYTHON:-$(command -v python)}"
exec "${LAUNCH_PYTHON:-$AGENT_SMITH_PYTHON}" scripts/manage.py run "$@"
