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

from src.agent_smith.services.seed import seed_all


async def cmd_init() -> None:
    await seed_all()
    print("Plan tools initialized.")


def main() -> int:
    parser = argparse.ArgumentParser(prog="scripts/plans.py")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("init")
    args = parser.parse_args()

    if args.command == "init":
        asyncio.run(cmd_init())
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
