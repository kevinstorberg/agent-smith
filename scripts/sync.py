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

from src.agent_smith.constants import ITEM_TYPES
from src.agent_smith.services.sync import AgentSmithSyncService
from src.settings import get_settings


async def _run() -> int:
    parser = argparse.ArgumentParser(prog="scripts/sync.py")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--item-type", choices=ITEM_TYPES)
    parser.add_argument("--item-id", type=int)
    args = parser.parse_args()

    device_name = get_settings().DEVICE_NAME
    if device_name:
        print(f"[device: {device_name}]")

    service = AgentSmithSyncService()
    if args.item_id:
        if not args.item_type:
            print("Error: --item-id requires --item-type")
            return 1
        message = await service.sync_item(item_type=args.item_type, item_id=args.item_id)
        if message.startswith("Not found:"):
            print(f"\n✗ {message}")
            return 1
        print(f"\n✓ {message}")
        return 0

    result = await service.sync_all(dry_run=args.dry_run)
    print(result["stdout"], end="")
    if result.get("stderr"):
        print(result["stderr"], end="")
    return 0 if result["success"] else 1


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
