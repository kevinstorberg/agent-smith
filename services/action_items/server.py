from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.shared.paths import bootstrap
bootstrap()

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from services.action_items import db
from services.action_items.contracts import Contract, Create, Delete, Move, Patch, PositiveInt, Query


class ItemInput(Contract):
    item_id: PositiveInt


class UpdateInput(ItemInput):
    changes: Patch


class DeleteInput(ItemInput):
    expected_revision: PositiveInt


class MoveInput(ItemInput, Move):
    pass


class ActionItemsMCP(FastMCP):
    async def call_tool(self, name, arguments):
        # FastMCP otherwise coerces primitives and drops unknown top-level fields.
        contract = _INPUTS.get(name)
        if contract is not None:
            try:
                contract.model_validate(arguments)
            except ValueError as error:
                raise ToolError(str(error)) from None
        return await super().call_tool(name, arguments)

    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.inputSchema = _INPUTS[tool.name].model_json_schema()
        return tools


_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
_INPUTS = {"action_item_list": Query, "action_item_get": ItemInput, "action_item_create": Create,
           "action_item_update": UpdateInput, "action_item_delete": DeleteInput, "action_item_move": MoveInput}


def action_item_list(q: str | None = None, status: str = "open", project: str | None = None,
                     tags: list[str] | None = None, sort: str | None = None, limit: int = 10, offset: int = 0) -> dict[str, Any]:
    """Search title/description and list tasks. Status: open, completed, all. All supplied tags must match.

    Sort: manual (open only), completed (completed only), newest, updated, title.
    Defaults: open/manual, completed/completed, all/newest. Limit 1-100, offset nonnegative.
    """
    return db.list_items({"q": q, "status": status, "project": project, "tags": tags or [], "sort": sort, "limit": limit, "offset": offset})


def action_item_get(item_id: PositiveInt) -> dict[str, Any]:
    """Read the full task and its current revision before updating, deleting, or moving it."""
    return db.get(item_id)


def action_item_create(title: str, description: str = "", project: str | None = None, tags: list[str] | None = None,
                       status: str = "open", request_id: str | None = None) -> dict[str, Any]:
    """Create a task. Only title is required; status is open or completed.

    Supply a UUID request_id and reuse it with the original input after uncertain failures.
    Replay returns the current task without resetting edits/completion. Different input or a deleted task conflicts.
    """
    return db.create({"title": title, "description": description, "project": project, "tags": tags or [], "status": status, "request_id": request_id})


def action_item_update(item_id: PositiveInt, changes: Patch) -> dict[str, Any]:
    """Edit or complete/reopen a task through changes.status (open/completed), never a toggle.

    changes.expected_revision is required from a recent get/list. Omitted fields stay unchanged;
    project:null, description:null/empty, and tags:[] clear fields. On conflict reread before retrying.
    """
    return db.update(item_id, changes)


def action_item_delete(item_id: PositiveInt, expected_revision: PositiveInt) -> dict[str, Any]:
    """Delete a task using its current revision. Deleted tasks cannot be restored or recreated by request-ID replay."""
    return db.delete(item_id, Delete(expected_revision=expected_revision))


def action_item_move(item_id: PositiveInt, expected_revision: PositiveInt,
                     before_id: PositiveInt | None = None, after_id: PositiveInt | None = None) -> dict[str, Any]:
    """Move an open task immediately before OR after one other open task; supply exactly one anchor.

    Use the source task's current revision. The anchor's live position is resolved atomically, so
    after the page's last visible neighbor means after that neighbor, not the end of the entire queue.
    A stale source or unavailable anchor conflicts; reread before retrying.
    """
    return db.move(item_id, Move(expected_revision=expected_revision, before_id=before_id, after_id=after_id))


def create_server() -> ActionItemsMCP:
    server = ActionItemsMCP("action-items - create and manage a shared to-do list")
    for function in (action_item_list, action_item_get, action_item_create, action_item_update, action_item_delete, action_item_move):
        annotation = _READ if function in (action_item_list, action_item_get) else _WRITE
        if function is action_item_delete:
            annotation = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
        server.add_tool(function, annotations=annotation)
    return server


mcp = create_server()


if __name__ == "__main__":
    mcp.run()
