#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(prog="sync.py")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(repo_root))

    from scripts.shared.env import load_dotenv
    load_dotenv(repo_root)

    from services.db import init_db
    init_db()

    from scripts.shared.agents import AGENT_TARGETS
    from scripts.shared.fs import sync_rules, sync_skills
    from scripts.shared.mcp_utils import sync_mcp

    for agent in AGENT_TARGETS:
        print(f"[{agent}/rules]")
        sync_rules(agent, args.dry_run)
        print(f"[{agent}/skills]")
        sync_skills(agent, args.dry_run)
        print(f"[{agent}/mcp]")
        sync_mcp(agent, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
