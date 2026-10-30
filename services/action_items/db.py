from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

import psycopg2
from psycopg2.errors import LockNotAvailable, QueryCanceled
from psycopg2.extras import Json, RealDictCursor

from services.action_items.contracts import Create, Delete, Move, Patch, PositiveInt, Query
from services.db import get_connection
from pydantic import TypeAdapter

_WRITE_LOCK = "agent-smith:action-items-write"
_PUBLIC = "id, title, description, project, tags, status, completed_at, revision, created_at, updated_at"
_LIST = _PUBLIC.replace("description, ", "")
_SORTS = {"manual": "sort_key, id", "newest": "created_at DESC, id DESC", "updated": "updated_at DESC, id DESC",
          "title": "lower(title), id", "completed": "completed_at DESC, id DESC"}


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    pass


class StorageError(RuntimeError):
    pass


@contextmanager
def _cursor(*, write: bool = False):
    try:
        with get_connection() as connection, connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '6s'")
            if write:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (_WRITE_LOCK,))
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            yield cursor
    except (LockNotAvailable, QueryCanceled):
        raise Conflict("Action items are busy. Reread the item before retrying.") from None
    except psycopg2.Error as error:
        raise StorageError(f"Action item storage failed (SQLSTATE {error.pgcode or 'unknown'}). Reread before retrying.") from None


def _id(value: int) -> int:
    return TypeAdapter(PositiveInt).validate_python(value)


def _record(row: dict) -> dict:
    return {key: value.isoformat() if isinstance(value, datetime) else value for key, value in row.items()}


def _live(cursor, item_id: int, expected_revision: int | None = None) -> dict:
    cursor.execute("SELECT * FROM action_items WHERE id=%s AND deleted_at IS NULL" + (" FOR UPDATE" if expected_revision is not None else ""), (item_id,))
    row = cursor.fetchone()
    if row is None:
        raise NotFound("Action item not found or deleted")
    if expected_revision is not None and row["revision"] != expected_revision:
        raise Conflict("Action item changed. Reread it and use its current revision before saving.")
    return dict(row)


def _read(cursor, item_id: int) -> dict:
    cursor.execute(f"SELECT {_PUBLIC} FROM action_items WHERE id=%s AND deleted_at IS NULL", (item_id,))
    row = cursor.fetchone()
    if row is None:
        raise NotFound("Action item not found or deleted")
    return _record(row)


def _append_position(cursor) -> int:
    cursor.execute("SELECT COALESCE(MAX(sort_key),0)+1 AS position FROM action_items")
    return cursor.fetchone()["position"]


def _compact(cursor, position: int) -> None:
    cursor.execute("UPDATE action_items SET sort_key=sort_key-1 WHERE sort_key>%s", (position,))


def create(payload: Create | dict) -> dict:
    request = Create.model_validate(payload)
    original = request.model_dump(exclude={"request_id"})
    with _cursor(write=True) as cursor:
        if request.request_id is not None:
            cursor.execute("SELECT id, create_payload, deleted_at FROM action_items WHERE request_id=%s", (request.request_id,))
            previous = cursor.fetchone()
            if previous:
                if previous["deleted_at"] is not None:
                    raise Conflict("This creation request belongs to a deleted action item. Use a new request_id for a new item.")
                if previous["create_payload"] != original:
                    raise Conflict("This request_id was already used with different input. Replay the original input or use a new request_id.")
                return _read(cursor, previous["id"])
        cursor.execute("""INSERT INTO action_items(title,description,project,tags,status,completed_at,sort_key,request_id,create_payload)
            VALUES (%s,%s,%s,%s,%s,CASE WHEN %s='completed' THEN clock_timestamp() ELSE NULL END,%s,%s,%s) RETURNING id""",
            (request.title, request.description, request.project, request.tags, request.status, request.status,
             _append_position(cursor) if request.status == "open" else None, request.request_id, Json(original) if request.request_id else None))
        return _read(cursor, cursor.fetchone()["id"])


def get(item_id: int) -> dict:
    with _cursor() as cursor:
        return _read(cursor, _id(item_id))


def list_items(payload: Query | dict | None = None) -> dict:
    query = Query.model_validate(payload or {})
    predicates, values = ["deleted_at IS NULL"], []
    if query.status != "all":
        predicates.append("status=%s")
        values.append(query.status)
    if query.q is not None:
        predicates.append("(title ILIKE %s OR description ILIKE %s)")
        escaped = query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values.extend([f"%{escaped}%"] * 2)
    if query.project is not None:
        predicates.append("project=%s")
        values.append(query.project)
    if query.tags:
        predicates.append("tags @> %s::text[]")
        values.append(query.tags)
    where = " AND ".join(predicates)
    order = _SORTS[query.sort or {"open": "manual", "completed": "completed", "all": "newest"}[query.status]]
    with _cursor() as cursor:
        # Count and rows share one snapshot while another client changes the queue.
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cursor.execute(f"SELECT COUNT(*) AS total FROM action_items WHERE {where}", values)
        total = cursor.fetchone()["total"]
        cursor.execute(f"SELECT {_LIST} FROM action_items WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s", (*values, query.limit, query.offset))
        return {"items": [_record(row) for row in cursor.fetchall()], "total": total}


def update(item_id: int, payload: Patch | dict) -> dict:
    item_id, patch = _id(item_id), Patch.model_validate(payload)
    changes = patch.model_dump(exclude_unset=True, exclude={"expected_revision"})
    with _cursor(write=True) as cursor:
        before = _live(cursor, item_id, patch.expected_revision)
        changes = {key: value for key, value in changes.items() if value != before[key]}
        if not changes:
            return _read(cursor, item_id)
        if "status" in changes:
            if changes["status"] == "completed":
                changes["sort_key"] = None
                cursor.execute("SELECT clock_timestamp() AS completed_at")
                changes["completed_at"] = cursor.fetchone()["completed_at"]
            else:
                changes.update(sort_key=_append_position(cursor), completed_at=None)
        columns = ", ".join(f"{key}=%s" for key in changes)
        cursor.execute(f"UPDATE action_items SET {columns},revision=revision+1,updated_at=clock_timestamp() WHERE id=%s", (*changes.values(), item_id))
        if before["sort_key"] is not None and changes.get("status") == "completed":
            _compact(cursor, before["sort_key"])
        return _read(cursor, item_id)


def delete(item_id: int, payload: Delete | dict) -> dict:
    item_id, request = _id(item_id), Delete.model_validate(payload)
    with _cursor(write=True) as cursor:
        before = _live(cursor, item_id, request.expected_revision)
        cursor.execute("UPDATE action_items SET deleted_at=clock_timestamp(),sort_key=NULL,revision=revision+1,updated_at=clock_timestamp() WHERE id=%s", (item_id,))
        if before["sort_key"] is not None:
            _compact(cursor, before["sort_key"])
        return {"deleted": True, "id": item_id}


def move(item_id: int, payload: Move | dict) -> dict:
    item_id, request = _id(item_id), Move.model_validate(payload)
    anchor_id = request.before_id if request.before_id is not None else request.after_id
    if item_id == anchor_id:
        raise ValueError("The move anchor must be a different action item")
    with _cursor(write=True) as cursor:
        source = _live(cursor, item_id, request.expected_revision)
        cursor.execute("SELECT sort_key FROM action_items WHERE id=%s AND deleted_at IS NULL AND status='open' FOR UPDATE", (anchor_id,))
        anchor = cursor.fetchone()
        if source["sort_key"] is None or anchor is None:
            raise Conflict("The source and move anchor must still be open. Refresh the list before moving again.")
        old, target = source["sort_key"], anchor["sort_key"]
        target += (1 if request.after_id is not None else 0) - (1 if old < target else 0)
        if target == old:
            return _read(cursor, item_id)
        if target < old:
            cursor.execute("UPDATE action_items SET sort_key=sort_key+1 WHERE sort_key>=%s AND sort_key<%s", (target, old))
        else:
            cursor.execute("UPDATE action_items SET sort_key=sort_key-1 WHERE sort_key>%s AND sort_key<=%s", (old, target))
        cursor.execute("UPDATE action_items SET sort_key=%s,revision=revision+1,updated_at=clock_timestamp() WHERE id=%s", (target, item_id))
        return _read(cursor, item_id)
