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

from scripts.shared.agents import AGENT_TARGETS

_db_var = f"DATABASE_URL_{APP_ENV.upper()}"
DATABASE_URL: str = os.environ.get(_db_var, "")
if not DATABASE_URL:
    raise SystemExit(f"{_db_var} is required for APP_ENV={APP_ENV}. Set it in .env.{APP_ENV}")

if "pytest" in sys.modules and APP_ENV != "test":
    raise SystemExit(f"Tests can only run in APP_ENV=test, got APP_ENV={APP_ENV}.")

ALL_AGENTS: list[str] = list(AGENT_TARGETS)
DEVICE_NAME: str = os.environ.get("DEVICE_NAME", "my-space")
DASHBOARD_PORT: str = os.environ.get("DASHBOARD_PORT", "7654")
MCP_URL: str = f"http://localhost:{DASHBOARD_PORT}/mcp/"

MEMORY_STORE_PATH: str = os.environ.get("MEMORY_STORE_PATH", str(_repo_root / "memory_store"))
PINECONE_INDEX: str = os.environ.get("PINECONE_INDEX", "agent-smith-memories")
PINECONE_CLOUD: str = os.environ.get("PINECONE_CLOUD", "aws")
PINECONE_REGION: str = os.environ.get("PINECONE_REGION", "us-east-1")
