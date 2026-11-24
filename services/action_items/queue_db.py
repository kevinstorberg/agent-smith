from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from psycopg2.extras import Json

from services.action_items.ordering import Siblings
from services.action_items.queue_contracts import (
    EpicCreate,
    EpicPatch,
    EpicReference,
    EpicRemove,
    Membership,
    QueueMove,
)

_EPIC = "e.id,e.title,e.revision,e.created_at,e.updated_at,q.id AS entry_id,q.sort_key AS position"
_MEMBER = "q.id,q.action_item_id,a.status,a.deleted_at,q.parent_epic_id,q.sort_key"


def _tasks():
    from services.action_items import db
    return db


def siblings(parent_id: int | None = None) -> Siblings:
    return Siblings("action_item_queue_entries", "sibling_scope=%s", (f"epic:{parent_id}" if parent_id else "root",))


def task_entry(cursor, item_id: int) -> dict:
    cursor.execute("SELECT * FROM action_item_queue_entries WHERE action_item_id=%s FOR UPDATE", (item_id,))
    row = cursor.fetchone()
    if row is None:
        raise _tasks().StorageError("Global Action Item has no queue entry")
    return dict(row)


def bump_epics(cursor, *ids: int | None) -> None:
    values = sorted({value for value in ids if value is not None})
    if values:
        cursor.execute("UPDATE action_item_epics SET revision=revision+1,updated_at=clock_timestamp() WHERE id=ANY(%s)", (values,))


def create_task_entry(cursor, item_id: int, status: str) -> None:
    cursor.execute("INSERT INTO action_item_queue_entries(action_item_id,sort_key) VALUES(%s,%s)", (item_id, siblings().append_position(cursor) if status == "open" else None))


def task_activity(cursor, item_id: int, *, active: bool) -> None:
    entry = task_entry(cursor, item_id)
    old = entry["sort_key"]
    scope = siblings(entry["parent_epic_id"])
    position = scope.append_position(cursor) if active else None
    cursor.execute("UPDATE action_item_queue_entries SET sort_key=%s WHERE id=%s", (position, entry["id"]))
    if old is not None:
        scope.compact(cursor, old)
    bump_epics(cursor, entry["parent_epic_id"])


def _cohort(rows: list[dict]) -> str:
    values = [[r[key] for key in ("id", "action_item_id", "status", "deleted_at", "parent_epic_id", "sort_key")] for r in rows]
    values.sort(key=lambda row: row[0])
    encoded = json.dumps(values, default=str, separators=(",", ":")).encode()
    return "v1:" + hashlib.sha256(encoded).hexdigest()


def _member_rows(cursor, epic_id: int | None = None) -> list[dict]:
    condition = "q.parent_epic_id=%s" if epic_id is not None else "q.parent_epic_id IS NOT NULL"
    cursor.execute(f"SELECT {_MEMBER} FROM action_item_queue_entries q JOIN action_items a ON a.id=q.action_item_id WHERE {condition}", (epic_id,) if epic_id else ())
    return [dict(row) for row in cursor.fetchall()]


def _epic(cursor, epic_id: int, *, expected=None) -> dict:
    cursor.execute(f"SELECT {_EPIC} FROM action_item_epics e JOIN action_item_queue_entries q ON q.epic_id=e.id WHERE e.id=%s AND e.deleted_at IS NULL FOR UPDATE OF e,q", (epic_id,))
    row = cursor.fetchone()
    if row is None:
        raise _tasks().NotFound("Epic not found or removed")
    result = _tasks()._record(row)
    result["cohort"] = _cohort(_member_rows(cursor, epic_id))
    if expected is not None:
        if result["revision"] != expected.expected_revision or (getattr(expected, "cohort", None) is not None and result["cohort"] != expected.cohort):
            raise _tasks().Conflict("Epic membership or order changed. Refresh before saving again.")
    return result


def _check_parent(cursor, entry: dict, expected: EpicReference | None) -> None:
    if entry["parent_epic_id"] != (expected.id if expected else None):
        raise _tasks().Conflict("Action Item changed Epic. Refresh before moving again.")
    if expected:
        _epic(cursor, expected.id, expected=expected)


def _bump_items(cursor, ids: list[int]) -> None:
    if ids:
        cursor.execute("UPDATE action_items SET revision=revision+1,updated_at=clock_timestamp() WHERE id=ANY(%s) AND deleted_at IS NULL", (ids,))


def _move_membership(cursor, item_id: int, request: Membership, *, destination_id: int | None = None) -> None:
    task = _tasks()._live(cursor, item_id, _tasks()._Scope(None), request.expected_revision)
    entry = task_entry(cursor, item_id)
    _check_parent(cursor, entry, request.expected_parent)
    if request.destination is not None:
        _epic(cursor, request.destination.id, expected=request.destination)
        destination_id = request.destination.id
    parent = entry["parent_epic_id"]
    if parent == destination_id:
        return
    source = siblings(parent)
    old = entry["sort_key"]
    cursor.execute("UPDATE action_item_queue_entries SET sort_key=NULL WHERE id=%s", (entry["id"],))
    if old is not None:
        source.compact(cursor, old)
    position = None
    if task["status"] == "open":
        if destination_id is None and parent is not None:
            epic = _epic(cursor, parent)
            position = epic["position"] + 1
            cursor.execute("UPDATE action_item_queue_entries SET sort_key=sort_key+1 WHERE sibling_scope='root' AND sort_key>=%s", (position,))
        else:
            position = siblings(destination_id).append_position(cursor)
    cursor.execute("UPDATE action_item_queue_entries SET parent_epic_id=%s,sort_key=%s WHERE id=%s", (destination_id, position, entry["id"]))
    _bump_items(cursor, [item_id])
    bump_epics(cursor, parent, destination_id)


def create_epic(payload: EpicCreate | dict) -> dict:
    request = EpicCreate.model_validate(payload)
    original = request.model_dump(mode="json", exclude={"request_id"})
    with _tasks()._cursor(None, write=True) as (cursor, _):
        cursor.execute("SELECT id,create_payload,deleted_at FROM action_item_epics WHERE request_id=%s", (request.request_id,))
        previous = cursor.fetchone()
        if previous:
            if previous["deleted_at"] is not None or previous["create_payload"] != original:
                raise _tasks().Conflict("This Epic request_id was already used. Replay the original request or use a new request_id.")
            return _epic(cursor, previous["id"])
        cursor.execute("INSERT INTO action_item_epics(title,request_id,create_payload) VALUES(%s,%s,%s) RETURNING id", (request.title, request.request_id, Json(original)))
        epic_id = cursor.fetchone()["id"]
        cursor.execute("INSERT INTO action_item_queue_entries(epic_id,sort_key) VALUES(%s,%s)", (epic_id, siblings().append_position(cursor)))
        if request.item_id is not None:
            _move_membership(cursor, request.item_id, request.membership, destination_id=epic_id)
        return _epic(cursor, epic_id)


def rename_epic(epic_id: int, payload: EpicPatch | dict) -> dict:
    epic_id = _tasks()._id(epic_id)
    request = EpicPatch.model_validate(payload)
    with _tasks()._cursor(None, write=True) as (cursor, _):
        before = _epic(cursor, epic_id, expected=request)
        if request.title != before["title"]:
            cursor.execute("UPDATE action_item_epics SET title=%s,revision=revision+1,updated_at=clock_timestamp() WHERE id=%s", (request.title, epic_id))
        return _epic(cursor, epic_id)


def remove_epic(epic_id: int, payload: EpicRemove | dict) -> dict:
    epic_id = _tasks()._id(epic_id)
    request = EpicRemove.model_validate(payload)
    with _tasks()._cursor(None, write=True) as (cursor, _):
        before = _epic(cursor, epic_id, expected=request)
        cursor.execute("SELECT q.id,q.action_item_id,q.sort_key FROM action_item_queue_entries q WHERE parent_epic_id=%s ORDER BY sort_key NULLS LAST,id FOR UPDATE", (epic_id,))
        members = [dict(row) for row in cursor.fetchall()]
        active = [row for row in members if row["sort_key"] is not None]
        position = before["position"]
        cursor.execute("UPDATE action_item_queue_entries SET sort_key=NULL WHERE epic_id=%s", (epic_id,))
        cursor.execute("UPDATE action_item_queue_entries SET sort_key=sort_key+%s WHERE sibling_scope='root' AND sort_key>%s", (len(active)-1, position))
        cursor.execute("UPDATE action_item_queue_entries SET parent_epic_id=NULL,sort_key=NULL WHERE parent_epic_id=%s", (epic_id,))
        for index, row in enumerate(active):
            cursor.execute("UPDATE action_item_queue_entries SET sort_key=%s WHERE id=%s", (position+index, row["id"]))
        _bump_items(cursor, [row["action_item_id"] for row in members])
        cursor.execute("UPDATE action_item_epics SET deleted_at=clock_timestamp(),updated_at=clock_timestamp(),revision=revision+1 WHERE id=%s", (epic_id,))
        return {"deleted": True, "id": epic_id}


def set_membership(item_id: int, payload: Membership | dict) -> dict:
    item_id = _tasks()._id(item_id)
    request = Membership.model_validate(payload)
    with _tasks()._cursor(None, write=True) as (cursor, scope):
        _move_membership(cursor, item_id, request)
        return _tasks()._read(cursor, item_id, scope)


def legacy_move(cursor, source: dict, anchor_id: int, *, after: bool) -> None:
    entry = task_entry(cursor, source["id"])
    cursor.execute("SELECT q.* FROM action_item_queue_entries q JOIN action_items a ON a.id=q.action_item_id WHERE a.id=%s AND a.deleted_at IS NULL AND a.status='open' FOR UPDATE OF q,a", (anchor_id,))
    anchor = cursor.fetchone()
    if source["status"] != "open" or anchor is None:
        raise _tasks().Conflict("The source and move anchor must still be open. Refresh before moving again.")
    if anchor["parent_epic_id"] != entry["parent_epic_id"]:
        raise _tasks().Conflict("These Action Items are in different Epic scopes. Use Move to Epic in the Action Items UI to change membership.")
    _reorder(cursor, entry, anchor, after=after)


def _reorder(cursor, source: dict, anchor: dict, *, after: bool) -> None:
    old, target = source["sort_key"], anchor["sort_key"]
    if old is None or target is None:
        raise _tasks().Conflict("Only live open items and Epics can be reordered")
    target += int(after)-int(old < target)
    if not siblings(source["parent_epic_id"]).move(cursor, source["id"], old, target):
        return
    if source["action_item_id"]:
        _bump_items(cursor, [source["action_item_id"]])
        bump_epics(cursor, source["parent_epic_id"])
    else:
        rows = _member_rows(cursor, source["epic_id"])
        _bump_items(cursor, [row["action_item_id"] for row in rows])
        bump_epics(cursor, source["epic_id"])


def move(payload: QueueMove | dict) -> dict:
    request = QueueMove.model_validate(payload)
    with _tasks()._cursor(None, write=True) as (cursor, _):
        def resolve(reference):
            if reference.kind == "epic":
                epic = _epic(cursor, reference.id, expected=reference)
                cursor.execute("SELECT * FROM action_item_queue_entries WHERE id=%s", (epic["entry_id"],))
                return dict(cursor.fetchone())
            task = _tasks()._live(cursor, reference.id, _tasks()._Scope(None), reference.expected_revision)
            if task["status"] != "open":
                raise _tasks().Conflict("Only open Action Items can be reordered")
            return task_entry(cursor, reference.id)
        source, anchor = resolve(request.source), resolve(request.before or request.after)
        _check_parent(cursor, source, request.parent)
        if source["parent_epic_id"] != anchor["parent_epic_id"]:
            raise _tasks().Conflict("Move anchors must have the same parent. Use Move to Epic for membership.")
        _reorder(cursor, source, anchor, after=request.after is not None)
        return {"saved": True}


def _catalog(cursor) -> list[dict]:
    members = defaultdict(list)
    for row in _member_rows(cursor):
        members[row["parent_epic_id"]].append(row)
    cursor.execute(f"SELECT {_EPIC} FROM action_item_epics e JOIN action_item_queue_entries q ON q.epic_id=e.id WHERE e.deleted_at IS NULL ORDER BY lower(e.title),e.id")
    result = []
    for record in cursor.fetchall():
        epic = _tasks()._record(record)
        epic["cohort"] = _cohort(members[epic["id"]])
        epic["total_count"] = sum(row["deleted_at"] is None for row in members[epic["id"]])
        result.append(epic)
    return result


def list_epics() -> dict:
    with _tasks()._cursor(None, write=False) as (cursor, _):
        return {"items": _catalog(cursor)}


def _sort_values(records: list[dict], key, sort: str) -> list[dict]:
    descending = sort in {"manual_desc", "title_desc", "updated", "newest", "completed", "tags_desc", "project_desc", "due_desc"}
    present, missing = [], []
    for record in records:
        (missing if key(record) is None else present).append(record)
    def identity(row):
        return (row.get("kind", "item"), row.get("item", row.get("epic", row))["id"])
    return sorted(present, key=lambda row: (key(row), identity(row)), reverse=descending) + sorted(missing, key=identity, reverse=descending)


def _task_value(item: dict, position: int | None, sort: str):
    if sort.startswith("manual"):
        return position
    if sort.startswith("title"):
        return item["title"].lower()
    if sort.startswith("updated"):
        return item["updated_at"]
    if sort == "newest":
        return item["created_at"]
    if sort == "completed":
        return item["completed_at"]
    if sort.startswith("due"):
        return item["due_at"]
    if sort.startswith("project"):
        return item["project"].lower() if item["project"] else None
    return tuple(item["tags"]) or None


def _root_value(root: dict, sort: str):
    if root["kind"] == "item":
        return _task_value(root["item"], root["position"], sort)
    epic = root["epic"]
    if sort.startswith("manual"):
        return epic["position"]
    if sort.startswith("title"):
        return epic["title"].lower()
    if sort == "newest":
        return epic["created_at"]
    values = [_task_value(child["item"], child["position"], sort) for child in root["children"]]
    values = [value for value in values if value is not None]
    if sort.startswith("updated"):
        return max([epic["updated_at"], *values])
    if not values:
        return None
    # One aggregate per column keeps direction reversal meaningful for the same cohort.
    return max(values) if sort == "completed" else min(values)


def list_queue(payload=None) -> dict:
    from services.action_items.contracts import Query
    from services.api.models.shared.listing import search_pattern

    query = Query.model_validate(payload or {})
    sort = query.sort or {"open": "manual", "completed": "completed", "all": "newest"}[query.status]
    with _tasks()._cursor(None, write=False) as (cursor, scope):
        predicates, values = ["a.profile_id IS NULL", "a.deleted_at IS NULL"], []
        if query.status != "all":
            predicates.append("a.status=%s")
            values.append(query.status)
        if query.q:
            predicates.append("(a.title ILIKE %s OR a.description ILIKE %s OR e.title ILIKE %s)")
            values.extend([search_pattern(query.q)]*3)
        if query.project:
            predicates.append("p.name=%s")
            values.append(_tasks()._project_name(cursor, query.project))
        if query.unassigned:
            predicates.append("a.project_id IS NULL")
        if query.tags:
            predicates.append("a.tags @> %s::text[]")
            values.append(query.tags)
        if query.due_within_hours is not None:
            predicates.append("a.due_at <= CURRENT_TIMESTAMP + make_interval(hours => %s)")
            values.append(query.due_within_hours)
        cursor.execute(f"""SELECT {scope.columns(detail=False)},q.id AS entry_id,q.parent_epic_id,q.sort_key AS position
          FROM {_tasks()._PROJECT_ROWS} JOIN action_item_queue_entries q ON q.action_item_id=a.id
          LEFT JOIN action_item_epics e ON e.id=q.parent_epic_id
          WHERE {' AND '.join(predicates)}""", values)
        roots, children = [], defaultdict(list)
        for record in cursor.fetchall():
            item = _tasks()._record(record)
            entry = {key: item.pop(key) for key in ("entry_id", "parent_epic_id", "position")}
            entry.update(kind="item", item=item)
            if entry["parent_epic_id"] is None:
                roots.append(entry)
            else:
                children[entry["parent_epic_id"]].append(entry)
        item_constraints = bool(query.project or query.unassigned or query.tags or query.due_within_hours is not None)
        for epic in _catalog(cursor):
            matches = children[epic["id"]]
            include_empty = query.status != "completed" and not item_constraints and (not query.q or query.q.casefold() in epic["title"].casefold())
            if matches or include_empty:
                ordered = _sort_values(matches, lambda row: _task_value(row["item"], row["position"], sort), sort)
                roots.append({"kind": "epic", "epic": epic, "children": ordered, "matching_count": len(matches), "total_count": epic["total_count"]})
        ordered = _sort_values(roots, lambda row: _root_value(row, sort), sort)
        return {"items": ordered[query.offset:query.offset+query.limit], "total": len(roots), "matching_count": sum(1 if row["kind"] == "item" else row["matching_count"] for row in roots)}
