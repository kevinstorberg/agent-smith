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
    from services.api.models.shared.harness import VALID_ITEM_TYPES

    parser = argparse.ArgumentParser(prog="scripts/sync.py")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--item-type", choices=VALID_ITEM_TYPES)
    parser.add_argument("--item-id", type=int)
    args = parser.parse_args()

    from services.db import init_db
    init_db()

    device_name = os.environ.get("DEVICE_NAME", "")
    if device_name:
        print(f"[device: {device_name}]")

    if args.item_id:
        if not args.item_type:
            print("Error: --item-id requires --item-type")
            return 1

        from scripts.shared.fs import sync_item
        result = sync_item(args.item_type, args.item_id, device_name)

        if result["success"]:
            print(f"\n✓ {result['message']}")
            return 0
        else:
            print(f"\n✗ {result['message']}")
            return 1

    from scripts.shared.agents import AGENT_TARGETS
    from scripts.shared.fs import sync_rules, sync_skills, sync_agents
    from scripts.shared.mcp_utils import sync_mcp
    from scripts.shared.hook_utils import sync_hooks

    for agent in AGENT_TARGETS:
        print(f"[{agent}/rules]")
        sync_rules(agent, args.dry_run, device_name=device_name)
        print(f"[{agent}/skills]")
        sync_skills(agent, args.dry_run, device_name=device_name)
        print(f"[{agent}/mcp]")
        sync_mcp(agent, args.dry_run)
        print(f"[{agent}/hooks]")
        sync_hooks(agent, args.dry_run)
        print(f"[{agent}/agents]")
        sync_agents(agent, args.dry_run, device_name=device_name)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
