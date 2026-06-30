from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ENV: str = os.environ.get("APP_ENV", "development")

_repo_root = Path(__file__).resolve().parent.parent
_env_default = _repo_root / ".env.default"
_env_file = _repo_root / f".env.{APP_ENV}"

if not _env_file.is_file() and not os.environ.get(f"DATABASE_URL_{APP_ENV.upper()}"):
    raise SystemExit(f".env.{APP_ENV} not found at {_env_file}. Create it for APP_ENV={APP_ENV}.")

from scripts.shared.env import _load_env_file

_load_env_file(_env_file)
_load_env_file(_env_default)

from scripts.shared.agents import AGENT_TARGETS, VIRTUAL_AGENTS

_db_var = f"DATABASE_URL_{APP_ENV.upper()}"
DATABASE_URL: str = os.environ.get(_db_var, "")
if not DATABASE_URL:
    raise SystemExit(f"{_db_var} is required for APP_ENV={APP_ENV}. Set it in .env.{APP_ENV}")

if "pytest" in sys.modules and APP_ENV != "test":
    raise SystemExit(f"Tests can only run in APP_ENV=test, got APP_ENV={APP_ENV}.")

ALL_AGENTS: list[str] = list(AGENT_TARGETS)
ASSIGNABLE_AGENTS: list[str] = [*ALL_AGENTS, *VIRTUAL_AGENTS]
DEVICE_NAME: str = os.environ.get("DEVICE_NAME", "my-space")
DASHBOARD_PORT: str = os.environ.get("DASHBOARD_PORT", "7654")
MCP_BASE: str = f"http://localhost:{DASHBOARD_PORT}"

JOB_POLL_INTERVAL: float = float(os.environ.get("JOB_POLL_INTERVAL", "5"))
JOB_DEFAULT_TIMEOUT: float = float(os.environ.get("JOB_DEFAULT_TIMEOUT", "300"))
JOB_MAX_OUTPUT_BYTES: int = int(os.environ.get("JOB_MAX_OUTPUT_BYTES", "65536"))

# DB connection pool + transient-error resilience. The pool is fixed-size
# (minconn == maxconn == DB_POOL_MAX) so returned connections stay warm; see
# services/db/pool.py.
DB_POOL_MAX: int = int(os.environ.get("DB_POOL_MAX", "25"))
DB_CONNECT_TIMEOUT: float = float(os.environ.get("DB_CONNECT_TIMEOUT", "5"))
DB_CONNECT_MAX_ATTEMPTS: int = int(os.environ.get("DB_CONNECT_MAX_ATTEMPTS", "3"))
DB_CONNECT_BACKOFF_BASE: float = float(os.environ.get("DB_CONNECT_BACKOFF_BASE", "0.1"))
DB_CONNECT_BACKOFF_MAX: float = float(os.environ.get("DB_CONNECT_BACKOFF_MAX", "1.0"))
DB_POOL_PRE_PING: bool = os.environ.get("DB_POOL_PRE_PING", "false").lower() in ("1", "true", "yes")

# Sync reads destination agent config files (~/.claude.json, etc.) that the live
# agent app rewrites continuously, so a read can catch the file mid-write (a torn
# read = momentarily invalid JSON). Retry the read a few times before treating it
# as genuine, unfixable corruption. See scripts/shared/agents.py::read_with_retry.
SYNC_READ_MAX_ATTEMPTS: int = int(os.environ.get("SYNC_READ_MAX_ATTEMPTS", "3"))
SYNC_READ_BACKOFF: float = float(os.environ.get("SYNC_READ_BACKOFF", "0.1"))

MEMORY_STORE_PATH: str = os.environ.get("MEMORY_STORE_PATH", str(_repo_root / "memory_store"))
PINECONE_INDEX: str = os.environ.get("PINECONE_INDEX", "agent-smith-memories")
PINECONE_CLOUD: str = os.environ.get("PINECONE_CLOUD", "aws")
PINECONE_REGION: str = os.environ.get("PINECONE_REGION", "us-east-1")
