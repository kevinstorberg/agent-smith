from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def register_tool() -> dict[str, int | bool]:
    from psycopg2.errors import UniqueViolation

    from services.api.models.shared.harness import create_item
    from services.api.models.tool import get_tool
    from services.config import ALL_AGENTS

    existing = get_tool("repos")
    if existing is not None:
        return {"id": existing["id"], "created": False}
    try:
        item_id = create_item(
            "tool",
            "repos",
            content={
                "body": "Local repository cleanup; previews by default and requires explicit execution for deletion.",
                "metadata": {
                    "command": "${AGENT_SMITH_PYTHON}",
                    "args": ["${AGENT_SMITH_ROOT}/services/repositories/server.py"],
                    "description": "Preview and delete merged worktrees and branches locally",
                },
            },
            agents=ALL_AGENTS,
        )
    except UniqueViolation:
        existing = get_tool("repos")
        if existing is None:
            raise
        return {"id": existing["id"], "created": False}
    return {"id": item_id, "created": True}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Register the local repository cleanup MCP tool"
    )
    parser.add_argument("command", choices=["init"])
    parser.parse_args()
    from scripts.shared.paths import bootstrap

    bootstrap()
    print(json.dumps(register_tool()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
