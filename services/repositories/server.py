from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from scripts.shared.repository_cleanup import cleanup_repository
from services.mcp_contracts import ContractMCP


class CleanupRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    repository_path: str = Field(min_length=1, max_length=4096)
    execute: bool = False
    force: bool = False
    delete_remote: bool = False


def cleanup_merged_worktrees(
    repository_path: str,
    execute: bool = False,
    force: bool = False,
    delete_remote: bool = False,
) -> dict[str, Any]:
    """Preview merged-PR worktrees and branches in one absolute local repository path.

    Set execute=true only when the user requests deletion. Force allows destruction
    of dirty merged worktrees; protected branches, active/locked worktrees and
    unmerged commits remain protected. Set delete_remote=true explicitly to remove
    verified origin branches too. Does not pull, switch branches or stop processes.
    Reports each eligible, skipped, removed or failed item and any partial failures.
    Runs locally through stdio and needs authenticated GitHub CLI, Git and lsof.
    """
    request = CleanupRequest.model_validate(
        {
            "repository_path": repository_path,
            "execute": execute,
            "force": force,
            "delete_remote": delete_remote,
        }
    )
    return cleanup_repository(**request.model_dump())


def create_server() -> ContractMCP:
    server = ContractMCP(
        "repos - clean merged local worktrees and branches",
        {"cleanup_merged_worktrees": CleanupRequest},
    )
    server.add_tool(
        cleanup_merged_worktrees,
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    return server


mcp = create_server()


if __name__ == "__main__":
    mcp.run()
