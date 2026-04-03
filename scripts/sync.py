#!/usr/bin/env -S .venv/bin/python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.shared.paths import bootstrap
bootstrap()


def main() -> int:
    import os

    parser = argparse.ArgumentParser(prog="scripts/sync.py")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from services.db import init_db
    init_db()

    device_name = os.environ.get("DEVICE_NAME", "")
    if device_name:
        print(f"[device: {device_name}]")

    from scripts.shared.agents import AGENT_TARGETS
    from scripts.shared.fs import sync_rules, sync_skills, sync_agents
    from scripts.shared.mcp_utils import sync_mcp

    for agent in AGENT_TARGETS:
        print(f"[{agent}/rules]")
        sync_rules(agent, args.dry_run, device_name=device_name)
        print(f"[{agent}/skills]")
        sync_skills(agent, args.dry_run, device_name=device_name)
        print(f"[{agent}/mcp]")
        sync_mcp(agent, args.dry_run)
        print(f"[{agent}/agents]")
        sync_agents(agent, args.dry_run, device_name=device_name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
