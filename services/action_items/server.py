from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.shared.paths import bootstrap

bootstrap()

from mcp.types import ToolAnnotations

from services.action_items import db
from services.action_items.contracts import (
    Contract,
    Create,
    Delete,
    Move,
    Patch,
    PositiveInt,
    ProjectCreate,
    Query,
)
from services.mcp_contracts import ContractMCP


class ItemInput(Contract):
    item_id: PositiveInt


class UpdateInput(ItemInput):
    changes: Patch


class DeleteInput(ItemInput):
    expected_revision: PositiveInt


class MoveInput(ItemInput, Move):
    pass


class ProjectInput(Contract):
    project_id: PositiveInt


class ActionItemsMCP(ContractMCP):
    def __init__(self, name: str) -> None:
        super().__init__(name, _INPUTS)


_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
_INPUTS = {
    "action_item_list": Query,
    "action_item_get": ItemInput,
    "action_item_create": Create,
    "action_item_update": UpdateInput,
    "action_item_delete": DeleteInput,
    "action_item_move": MoveInput,
    "action_item_project_list": Contract,
    "action_item_project_create": ProjectCreate,
    "action_item_project_delete": ProjectInput,
}


def action_item_list(
    q: str | None = None,
    status: str = "open",
    project: str | None = None,
    tags: list[str] | None = None,
    sort: str | None = None,
    limit: int = 10,
    offset: int = 0,
    unassigned: bool = False,
    due_within_hours: int | None = None,
) -> dict[str, Any]:
    """Search title/description and list tasks. Status: open, completed, all. All supplied tags must match.

    Sort: manual (open only), completed (completed only), newest, updated, title.
    Defaults: open/manual, completed/completed, all/newest. Limit 1-100, offset nonnegative.
    Project names match exactly; unassigned=true selects tasks without a project and cannot combine with project.
    due_within_hours (1-168) includes past deadlines and deadlines within that many hours; undated tasks are excluded.
    Status still applies: Open is the default, and Completed/All include matching historical deadlines.
    """
    return db.list_items(
        {
            "q": q,
            "status": status,
            "project": project,
            "tags": [] if tags is None else tags,
            "sort": sort,
            "limit": limit,
            "offset": offset,
            "unassigned": unassigned,
            "due_within_hours": due_within_hours,
        }
    )


def action_item_get(item_id: PositiveInt) -> dict[str, Any]:
    """Read the full task and its current revision before updating, deleting, or moving it."""
    return db.get(item_id)


def action_item_create(
    title: str,
    description: str = "",
    project: str | None = None,
    tags: list[str] | None = None,
    status: str = "open",
    request_id: str | None = None,
    due_at: str | None = None,
) -> dict[str, Any]:
    """Create a task. Only title is required; status is open or completed.

    Supply a UUID request_id and reuse it with the original input after uncertain failures.
    Replay returns the current task without resetting edits/completion. Different input or a deleted task conflicts.
    due_at is an optional ISO datetime with an explicit timezone and at most six fractional digits; storage and output use UTC.
    """
    return db.create(
        {
            "title": title,
            "description": description,
            "project": project,
            "tags": [] if tags is None else tags,
            "status": status,
            "request_id": request_id,
            "due_at": due_at,
        }
    )


def action_item_update(item_id: PositiveInt, changes: Patch) -> dict[str, Any]:
    """Edit or complete/reopen a task through changes.status (open/completed), never a toggle.

    changes.expected_revision is required from a recent get/list. Omitted fields stay unchanged;
    project:null, due_at:null, description:null/empty, and tags:[] clear fields. Due dates require an explicit timezone.
    Completing or reopening retains the deadline. On conflict reread before retrying.
    """
    return db.update(item_id, changes)


def action_item_delete(
    item_id: PositiveInt, expected_revision: PositiveInt
) -> dict[str, Any]:
    """Delete a task using its current revision. Deleted tasks cannot be restored or recreated by request-ID replay."""
    return db.delete(item_id, Delete(expected_revision=expected_revision))


def action_item_move(
    item_id: PositiveInt,
    expected_revision: PositiveInt,
    before_id: PositiveInt | None = None,
    after_id: PositiveInt | None = None,
) -> dict[str, Any]:
    """Move an open task immediately before OR after one other open task; supply exactly one anchor.

    Use the source task's current revision. The anchor's live position is resolved atomically, so
    after the page's last visible neighbor means after that neighbor, not the end of the entire queue.
    A stale source or unavailable anchor conflicts; reread before retrying.
    """
    return db.move(
        item_id,
        Move(
            expected_revision=expected_revision, before_id=before_id, after_id=after_id
        ),
    )


def action_item_project_list() -> dict[str, Any]:
    """List the project catalog, including projects with no tasks. Projects and tags are independent."""
    return db.list_projects()


def action_item_project_create(name: str) -> dict[str, Any]:
    """Create an empty project, or return its existing exact name. Names preserve case.

    New names are trimmed, contain 1-200 characters, and cannot contain control characters.
    """
    return db.create_project({"name": name})


def action_item_project_delete(project_id: PositiveInt) -> dict[str, Any]:
    """Delete a project only when no task references it, including completed and deleted tasks."""
    return db.delete_project(project_id)


def create_server() -> ActionItemsMCP:
    server = ActionItemsMCP("action-items - create and manage a shared to-do list")
    for function in (
        action_item_list,
        action_item_get,
        action_item_create,
        action_item_update,
        action_item_delete,
        action_item_move,
        action_item_project_list,
        action_item_project_create,
        action_item_project_delete,
    ):
        annotation = (
            _READ
            if function in (action_item_list, action_item_get, action_item_project_list)
            else _WRITE
        )
        if function in (action_item_delete, action_item_project_delete):
            annotation = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
        server.add_tool(function, annotations=annotation)
    return server


mcp = create_server()


if __name__ == "__main__":
    mcp.run()
