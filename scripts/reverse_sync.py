#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) in sys.path:
    sys.path.remove(str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asyncio

from src.agent_smith.constants import ALL_AGENTS
from src.agent_smith.services.sync import AgentSmithSyncService


async def _run() -> int:
    parser = argparse.ArgumentParser(prog="reverse_sync.py")
    parser.add_argument("--agent", choices=ALL_AGENTS, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = await AgentSmithSyncService().reverse_sync(agent=args.agent, dry_run=args.dry_run)
    print(result["stdout"], end="")
    if result.get("stderr"):
        print(result["stderr"], end="")
    return 0 if result["success"] else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
