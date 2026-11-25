from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from scripts.shared.paths import bootstrap

bootstrap()

from mcp.types import ToolAnnotations

from services.action_items import db, queue_db
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
from services.action_items.queue_contracts import (
    EntryReference,
    EpicCreate,
    EpicPatch,
    EpicReference,
    EpicRemove,
    Membership,
    QueueMove,
    QueueQuery,
    QueueEdge,
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


class QueueInput(Contract):
    filters: QueueQuery | None = None


class EpicRenameInput(EpicPatch):
    epic_id: PositiveInt


class EpicDeleteInput(EpicRemove):
    epic_id: PositiveInt


class MembershipInput(ItemInput, Membership):
    pass


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
    "action_item_queue_list": QueueInput,
    "action_item_queue_move": QueueMove,
    "action_item_epic_list": Contract,
    "action_item_epic_create": EpicCreate,
    "action_item_epic_rename": EpicRenameInput,
    "action_item_epic_delete": EpicDeleteInput,
    "action_item_set_epic": MembershipInput,
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

    Sort: manual/manual_desc (open only), completed (completed only), newest,
    title/title_desc, updated_asc/updated, tags_asc/tags_desc,
    project_asc/project_desc, due_asc/due_desc. Missing values sort last.
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
    Source and anchor must share the same Epic scope. Cross-scope moves return a conflict;
    use action_item_set_epic to explicitly change Epic membership.
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


def action_item_queue_list(filters: QueueQuery | None = None) -> dict[str, Any]:
    """Read grouped Action Items, Epic membership and current structural revisions before changing groups or order.

    filters accepts the same fields as action_item_list plus kind=all, epic, item, task; status defaults to open.
    all/epic retain grouped roots; item retains standalone tasks. task returns every matching task,
    including Epic members, with its explicit parent snapshot and global priority before task pagination.
    task totals count tasks; root_total/root_index count matching nonempty roots for scoped root actions.
    Use status=all to inspect completed members too. Grouped pagination counts root groups,
    and each returned Epic includes all matching children without splitting the Epic.
    Epic revision/cohort and child revisions are live snapshots; reread after each mutation.
    Sort applies within each Epic as well as to root groups; manual preserves saved sibling order.
    """
    return queue_db.list_queue(filters)


def action_item_queue_move(
    source: EntryReference,
    parent: EpicReference | None = None,
    before: EntryReference | None = None,
    after: EntryReference | None = None,
    edge: QueueEdge | None = None,
) -> dict[str, Any]:
    """Reorder a root Epic/standalone task or reorder tasks WITHIN one Epic, using fresh queue snapshots.

    Supply exactly one before/after anchor or edge. Anchors include their current expected_revision.
    edge=top/bottom requires an item source and its Epic parent; it uses every open sibling,
    including siblings hidden by filters. Actual-edge requests are no-ops after snapshot validation.
    Epic references also require cohort. For Epic children, parent must identify their shared Epic.
    Source and anchor must share the same parent; use action_item_set_epic for membership changes.
    Stale source, anchor or parent snapshots conflict; reread action_item_queue_list before retrying.
    """
    return queue_db.move(
        QueueMove(source=source, parent=parent, before=before, after=after, edge=edge)
    )


def action_item_epic_list() -> dict[str, Any]:
    """List all live Epics, including empty groups, with their current revisions, cohorts and member counts.

    Use action_item_queue_list with filters.status=all to inspect member tasks and their ordering.
    """
    return queue_db.list_epics()


def action_item_epic_create(
    title: str,
    request_id: str,
    item_id: PositiveInt | None = None,
    membership: Membership | None = None,
) -> dict[str, Any]:
    """Create an Epic, optionally grouping one existing Action Item in the same transaction.

    request_id must be a UUID; replay the original input after uncertain failures to avoid duplicates.
    For inline grouping supply both item_id and membership, with the task's current expected_revision
    and expected_parent snapshot when already grouped; membership.destination must be omitted.
    Empty Epics are supported. Use action_item_set_epic to group additional existing tasks.
    """
    return queue_db.create_epic(
        EpicCreate(
            title=title, request_id=request_id, item_id=item_id, membership=membership
        )
    )


def action_item_epic_rename(
    epic_id: PositiveInt, title: str, expected_revision: PositiveInt
) -> dict[str, Any]:
    """Rename an Epic using its current revision from action_item_epic_list or action_item_queue_list."""
    return queue_db.rename_epic(
        epic_id, EpicPatch(title=title, expected_revision=expected_revision)
    )


def action_item_epic_delete(
    epic_id: PositiveInt, expected_revision: PositiveInt, cohort: str
) -> dict[str, Any]:
    """Remove an Epic and unwrap its members into the root queue, preserving every Action Item.

    Supply the current Epic expected_revision and cohort from a fresh Epic/queue list.
    Changed membership or ordering conflicts rather than unwrapping an outdated selection.
    """
    return queue_db.remove_epic(
        epic_id, EpicRemove(expected_revision=expected_revision, cohort=cohort)
    )


def action_item_set_epic(
    item_id: PositiveInt,
    expected_revision: PositiveInt,
    expected_parent: EpicReference | None = None,
    destination: EpicReference | None = None,
) -> dict[str, Any]:
    """Assign or move an existing Action Item to an Epic, or ungroup it with destination=null.

    Read action_item_queue_list first. Supply the task's expected_revision and its expected_parent
    snapshot when grouped. Destination and parent references require id, expected_revision and cohort.
    Ungrouped source tasks use expected_parent=null. Membership changes return the updated task;
    reread Epic snapshots before the next mutation because membership changes their revisions.
    """
    return queue_db.set_membership(
        item_id,
        Membership(
            expected_revision=expected_revision,
            expected_parent=expected_parent,
            destination=destination,
        ),
    )


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
        action_item_queue_list,
        action_item_queue_move,
        action_item_epic_list,
        action_item_epic_create,
        action_item_epic_rename,
        action_item_epic_delete,
        action_item_set_epic,
    ):
        annotation = (
            _READ
            if function
            in (
                action_item_list,
                action_item_get,
                action_item_project_list,
                action_item_queue_list,
                action_item_epic_list,
            )
            else _WRITE
        )
        if function in (
            action_item_delete,
            action_item_project_delete,
            action_item_epic_delete,
        ):
            annotation = ToolAnnotations(readOnlyHint=False, destructiveHint=True)
        server.add_tool(function, annotations=annotation)
    return server


mcp = create_server()


if __name__ == "__main__":
    mcp.run()
