#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.shared.paths import bootstrap
bootstrap()


def cmd_init():
    from services.db import init_db
    from services.api.models.shared.harness import upsert_item
    from services.config import ALL_AGENTS, MCP_BASE
    init_db()

    upsert_item(
        "tool", "plans",
        content={"body": "", "metadata": {"url": f"{MCP_BASE}/mcp/plans/", "description": "Save and retrieve implementation plans"}},
        agents=ALL_AGENTS,
    )
    print("  registered: plans")
    print("Plan tools initialized.")


def main():
    parser = argparse.ArgumentParser(prog="scripts/plans.py")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init")
    args = parser.parse_args()

    if args.command == "init":
        cmd_init()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
