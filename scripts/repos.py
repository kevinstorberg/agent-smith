#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.shared.repository_cleanup import cleanup_repository


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview removal of GitHub-confirmed merged branches and linked worktrees."
    )
    parser.add_argument(
        "repository", help="Absolute path to the local GitHub repository"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute confirmed removals; default is preview",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow dirty merged worktree removal; all protection checks remain",
    )
    parser.add_argument(
        "--delete-remote",
        action="store_true",
        help="Include origin branches with exact expected-head leases",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    try:
        report = cleanup_repository(
            args.repository,
            execute=args.execute,
            force=args.force,
            delete_remote=args.delete_remote,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"repository": args.repository, "error": str(error)}))
        return 1
    print(json.dumps(report, indent=2))
    return int(
        bool(report.get("errors")) or bool(report.get("summary", {}).get("failed"))
    )


if __name__ == "__main__":
    raise SystemExit(main())
