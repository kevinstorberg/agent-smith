from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg2
from psycopg2.errors import LockNotAvailable, QueryCanceled
from psycopg2.extras import Json, RealDictCursor
from pydantic import TypeAdapter

from services.action_items.contracts import (
    Contract,
    Create,
    Delete,
    GLOBAL_ONLY_SORTS,
    Move,
    Patch,
    PositiveInt,
    ProjectCreate,
    ProjectMetadataCreate,
    ProjectPatch,
    ProjectQuery,
    Query,
)
from services.api.models.shared.listing import (
    bidirectional_sorts,
    search_pattern,
    sort_clause,
)
from services.db import get_connection
from services.meetings import profile_db
from services.meetings.db import MeetingStorageError

_WRITE_LOCK = "agent-smith:action-items-write"
_PROJECT_ROWS = "action_items a LEFT JOIN action_item_projects p ON p.id=a.project_id"
_PUBLIC = "a.id, a.title, a.description, p.name AS project, a.tags, a.status, a.completed_at, a.revision, a.created_at, a.updated_at, a.sort_key AS priority"
_LIST = _PUBLIC.replace("a.description, ", "")
_SORTS = {
    **bidirectional_sorts(
        {
            ("manual", "manual_desc"): ("a.sort_key",),
            ("title", "title_desc"): ("lower(a.title)",),
            ("updated_asc", "updated"): ("a.updated_at",),
            ("tags_asc", "tags_desc"): ("NULLIF(a.tags, '{}'::text[])",),
            ("project_asc", "project_desc"): ("lower(p.name)",),
            ("due_asc", "due_desc"): ("a.due_at",),
        },
        tie_breaker="a.id",
    ),
    "newest": "a.created_at DESC, a.id DESC",
    "completed": "a.completed_at DESC, a.id DESC",
}
_PROJECT_DETAIL = "id,name,description,revision,created_at,updated_at"
_PROJECT_SORTS = bidirectional_sorts(
    {
        ("name_asc", "name_desc"): ("lower(name)",),
        ("description_asc", "description_desc"): ("NULLIF(lower(description),'')",),
        ("updated_asc", "updated_desc"): ("updated_at",),
    }
)


class NotFound(LookupError):
    pass


class Conflict(RuntimeError):
    pass


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class _Scope:
    profile_id: str | None

    @property
    def key(self) -> str:
        return self.profile_id if self.profile_id is not None else "global"

    def columns(self, *, detail: bool) -> str:
        return (_PUBLIC if detail else _LIST) + (
            ", a.profile_id::text AS profile_id" if self.profile_id else ", a.due_at"
        )


@contextmanager
def _storage_errors():
    try:
        yield
    except (LockNotAvailable, QueryCanceled):
        raise Conflict(
            "Action items are busy. Reread the item before retrying."
        ) from None
    except profile_db.ProfileRevisionConflict as error:
        raise Conflict(str(error)) from None
    except MeetingStorageError as error:
        raise StorageError(str(error)) from None
    except psycopg2.Error as error:
        raise StorageError(
            f"Action item storage failed (SQLSTATE {error.pgcode or 'unknown'}). Reread before retrying."
        ) from None


def _resolve_scope(cursor, profile_id: str | None) -> _Scope:
    if profile_id is None:
        return _Scope(None)
    owner = profile_db.canonical_rows(cursor, [profile_id], metadata_only=True)[
        profile_id
    ]
    if owner is None or owner["deleted"]:
        raise NotFound("Discussion profile not found or deleted")
    return _Scope(str(owner["id"]))


@contextmanager
def _cursor(profile_id: str | None, *, write: bool):
    with _storage_errors(), ExitStack() as stack:
        if write and profile_id is not None:
            cursor = stack.enter_context(profile_db.profile_write_cursor())
        else:
            connection = stack.enter_context(get_connection())
            cursor = stack.enter_context(
                connection.cursor(cursor_factory=RealDictCursor)
            )
        with _storage_errors():
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '6s'")
            if write:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (_WRITE_LOCK,),
                )
            else:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            yield cursor, _resolve_scope(cursor, profile_id)


def _id(value: int) -> int:
    return TypeAdapter(PositiveInt).validate_python(value)


def _record(row: dict) -> dict:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in row.items()
    }


def _find_project(cursor, name: str) -> dict | None:
    cursor.execute(
        "SELECT id,name,created_at FROM action_item_projects WHERE name=%s", (name,)
    )
    row = cursor.fetchone()
    return dict(row) if row is not None else None


def _project_name(cursor, value: str | None) -> str | None:
    if value is None:
        return None
    existing = _find_project(cursor, value)
    if existing is not None:
        return existing["name"]
    if not value.strip():
        return None
    return ProjectCreate.model_validate({"name": value}).name


def _ensure_project(cursor, name: str | None, description: str = "") -> dict | None:
    if name is None:
        return None
    existing = _find_project(cursor, name)
    if existing is not None:
        return existing
    cursor.execute(
        "INSERT INTO action_item_projects(name,description) VALUES(%s,%s) ON CONFLICT(name) DO NOTHING RETURNING id,name,created_at",
        (name, description),
    )
    row = cursor.fetchone()
    return dict(row) if row is not None else _find_project(cursor, name)


def _same_creation(stored: dict, supplied: dict) -> bool:
    candidate = dict(supplied)
    original = stored.get("project")
    incoming = candidate.get("project")
    # Historical receipts own their normalization even when a new exact legacy name now exists.
    if isinstance(incoming, str) and (
        original is None or isinstance(original, str) and original == original.strip()
    ):
        normalized = incoming.strip() or None
        if normalized == original:
            candidate["project"] = normalized
    return stored == candidate


def list_projects() -> dict:
    with _cursor(None, write=False) as (cursor, _):
        cursor.execute(
            "SELECT id,name,created_at FROM action_item_projects ORDER BY lower(name),name,id"
        )
        rows = [_record(row) for row in cursor.fetchall()]
        return {"items": rows, "total": len(rows)}


def create_project(payload: ProjectCreate | dict) -> dict:
    request = ProjectCreate.model_validate(payload)
    with _cursor(None, write=True) as (cursor, _):
        return _record(_ensure_project(cursor, request.name))


def _project_details(cursor, project_id: int) -> dict:
    cursor.execute(
        f"SELECT {_PROJECT_DETAIL} FROM action_item_projects WHERE id=%s", (project_id,)
    )
    row = cursor.fetchone()
    if row is None:
        raise NotFound("Project not found")
    return _record(row)


def get_project_details(project_id: int) -> dict:
    project_id = _id(project_id)
    with _cursor(None, write=False) as (cursor, _):
        return _project_details(cursor, project_id)


def list_project_details(payload: ProjectQuery | dict) -> dict:
    query = ProjectQuery.model_validate(payload)
    order, pattern = sort_clause(query.sort, _PROJECT_SORTS), search_pattern(query.q)
    where = "WHERE name ILIKE %s OR description ILIKE %s" if pattern else ""
    values = (pattern, pattern) if pattern else ()
    with _cursor(None, write=False) as (cursor, _):
        cursor.execute(
            f"SELECT COUNT(*) AS total FROM action_item_projects {where}", values
        )
        total = cursor.fetchone()["total"]
        cursor.execute(
            f"SELECT {_PROJECT_DETAIL} FROM action_item_projects {where} ORDER BY {order} LIMIT %s OFFSET %s",
            (*values, query.limit, query.offset),
        )
        return {"items": [_record(row) for row in cursor.fetchall()], "total": total}


def create_project_details(payload: ProjectMetadataCreate | dict) -> dict:
    request = ProjectMetadataCreate.model_validate(payload)
    with _cursor(None, write=True) as (cursor, _):
        project = _ensure_project(cursor, request.name, request.description)
        result = _project_details(cursor, project["id"])
        if (
            "description" in request.model_fields_set
            and result["description"] != request.description
        ):
            raise Conflict(
                "A project with this name already exists. Edit that project to change its description."
            )
        return result


def update_project_details(project_id: int, payload: ProjectPatch | dict) -> dict:
    project_id, patch = _id(project_id), ProjectPatch.model_validate(payload)
    with _cursor(None, write=True) as (cursor, _):
        before = _project_details(cursor, project_id)
        if before["revision"] != patch.expected_revision:
            raise Conflict(
                "Project changed. Review the current saved version before saving again."
            )
        changes = {
            key: value
            for key, value in patch.model_dump(
                exclude_unset=True, exclude={"expected_revision"}
            ).items()
            if before[key] != value
        }
        if not changes:
            return before
        if "name" in changes:
            if _find_project(cursor, changes["name"]) is not None:
                raise Conflict(
                    "A project with this name already exists. Choose a different name."
                )
            # Existing item editors submit name-based assignments captured at their revision.
            cursor.execute(
                "UPDATE action_items SET revision=revision+1 WHERE project_id=%s AND deleted_at IS NULL",
                (project_id,),
            )
        columns = ", ".join(f"{key}=%s" for key in changes)
        cursor.execute(
            f"UPDATE action_item_projects SET {columns},revision=revision+1,updated_at=clock_timestamp() WHERE id=%s",
            (*changes.values(), project_id),
        )
        return _project_details(cursor, project_id)


def delete_project(project_id: int) -> dict:
    project_id = _id(project_id)
    with _cursor(None, write=True) as (cursor, _):
        cursor.execute(
            "SELECT id FROM action_item_projects WHERE id=%s FOR UPDATE", (project_id,)
        )
        if cursor.fetchone() is None:
            raise NotFound("Project not found")
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM action_items WHERE project_id=%s) AS referenced",
            (project_id,),
        )
        if cursor.fetchone()["referenced"]:
            raise Conflict(
                "Project is still referenced by action items, including deleted items"
            )
        cursor.execute("DELETE FROM action_item_projects WHERE id=%s", (project_id,))
        return {"deleted": True, "id": project_id}


def _live(cursor, item_id: int, scope: _Scope, expected_revision: int) -> dict:
    cursor.execute(
        f"SELECT a.*,p.name AS project FROM {_PROJECT_ROWS} WHERE a.id=%s AND a.scope_key=%s AND a.deleted_at IS NULL FOR UPDATE OF a",
        (item_id, scope.key),
    )
    row = cursor.fetchone()
    if row is None:
        raise NotFound("Action item not found or deleted")
    if row["revision"] != expected_revision:
        raise Conflict(
            "Action item changed. Reread it and use its current revision before saving."
        )
    return dict(row)


def _read(cursor, item_id: int, scope: _Scope) -> dict:
    cursor.execute(
        f"SELECT {scope.columns(detail=True)} FROM {_PROJECT_ROWS} WHERE a.id=%s AND a.scope_key=%s AND a.deleted_at IS NULL",
        (item_id, scope.key),
    )
    row = cursor.fetchone()
    if row is None:
        raise NotFound("Action item not found or deleted")
    return _record(row)


def _append_position(cursor, scope: _Scope) -> int:
    cursor.execute(
        "SELECT COALESCE(MAX(sort_key),0)+1 AS position FROM action_items WHERE scope_key=%s",
        (scope.key,),
    )
    return cursor.fetchone()["position"]


def _compact(cursor, position: int, scope: _Scope) -> None:
    cursor.execute(
        "UPDATE action_items SET sort_key=sort_key-1 WHERE scope_key=%s AND sort_key>%s",
        (scope.key, position),
    )


def merge_profile_queue(cursor, source_id: str, target_id: str) -> None:
    source, target = _Scope(str(UUID(source_id))), _Scope(str(UUID(target_id)))
    if source == target:
        raise ValueError("Select two different discussion profiles to merge")
    try:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (_WRITE_LOCK,)
        )
        offset = _append_position(cursor, target) - 1
        cursor.execute(
            """UPDATE action_items SET profile_id=%s,sort_key=sort_key+%s,
            revision=revision+1,updated_at=clock_timestamp() WHERE scope_key=%s""",
            (target.profile_id, offset, source.key),
        )
    except (LockNotAvailable, QueryCanceled):
        raise profile_db.ProfileRevisionConflict(
            "Discussion topics are busy; retry merging profiles."
        ) from None


@dataclass(frozen=True)
class Queue:
    profile_id: str | None

    def __post_init__(self) -> None:
        if self.profile_id is not None:
            if not isinstance(self.profile_id, str):
                raise ValueError("Queue profile_id must be a UUID string or None")
            object.__setattr__(self, "profile_id", str(UUID(self.profile_id)))

    def _validate_scope_fields(self, request: Contract) -> None:
        if (
            self.profile_id is not None
            and getattr(request, "sort", None) in GLOBAL_ONLY_SORTS
        ):
            raise ValueError(
                "Profile discussion topics do not support project or deadline sorting"
            )
        if self.profile_id is not None and request.model_fields_set & {
            "due_at",
            "due_within_hours",
        }:
            raise ValueError("Profile discussion topics do not support deadline fields")

    def create(self, payload: Create | dict) -> dict:
        request = Create.model_validate(payload)
        self._validate_scope_fields(request)
        original = request.model_dump(exclude={"request_id"})
        # Historical creation receipts have no deadline key; their original bytes remain authoritative.
        deadline = original.pop("due_at")
        if deadline is not None:
            original["due_at"] = deadline.isoformat()
        with _cursor(self.profile_id, write=True) as (cursor, scope):
            if request.request_id is not None:
                cursor.execute(
                    "SELECT id,create_payload,deleted_at FROM action_items WHERE request_id=%s AND scope_key=%s",
                    (request.request_id, scope.key),
                )
                previous = cursor.fetchone()
                if previous:
                    if previous["deleted_at"] is not None:
                        raise Conflict(
                            "This creation request belongs to a deleted action item. Use a new request_id for a new item."
                        )
                    if not _same_creation(previous["create_payload"], original):
                        raise Conflict(
                            "This request_id was already used with different input. Replay the original input or use a new request_id."
                        )
                    return _read(cursor, previous["id"], scope)
                # Request UUIDs remain globally reserved without exposing another queue's item.
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM action_items WHERE request_id=%s) AS reserved",
                    (request.request_id,),
                )
                if cursor.fetchone()["reserved"]:
                    raise Conflict(
                        "This request_id belongs to a different queue. Use a new request_id for a new item."
                    )
            original["project"] = _project_name(cursor, request.project)
            project = _ensure_project(cursor, original["project"])
            cursor.execute(
                """INSERT INTO action_items(title,description,project_id,tags,status,completed_at,sort_key,request_id,create_payload,profile_id,due_at)
                VALUES (%s,%s,%s,%s,%s,CASE WHEN %s='completed' THEN clock_timestamp() ELSE NULL END,%s,%s,%s,%s,%s) RETURNING id""",
                (
                    request.title,
                    request.description,
                    project["id"] if project else None,
                    request.tags,
                    request.status,
                    request.status,
                    _append_position(cursor, scope)
                    if request.status == "open"
                    else None,
                    request.request_id,
                    Json(original) if request.request_id else None,
                    scope.profile_id,
                    request.due_at,
                ),
            )
            return _read(cursor, cursor.fetchone()["id"], scope)

    def get(self, item_id: int) -> dict:
        item_id = _id(item_id)
        with _cursor(self.profile_id, write=False) as (cursor, scope):
            return _read(cursor, item_id, scope)

    def list_items(self, payload: Query | dict | None = None) -> dict:
        query = Query.model_validate(payload or {})
        self._validate_scope_fields(query)
        predicates, values = ["a.scope_key=%s", "a.deleted_at IS NULL"], []
        if query.status != "all":
            predicates.append("a.status=%s")
            values.append(query.status)
        if query.q is not None:
            predicates.append("(a.title ILIKE %s OR a.description ILIKE %s)")
            escaped = (
                query.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            values.extend([f"%{escaped}%"] * 2)
        if query.unassigned:
            predicates.append("a.project_id IS NULL")
        if query.due_within_hours is not None:
            predicates.append(
                "a.due_at <= CURRENT_TIMESTAMP + make_interval(hours => %s)"
            )
            values.append(query.due_within_hours)
        if query.tags:
            predicates.append("a.tags @> %s::text[]")
            values.append(query.tags)
        order = _SORTS[
            query.sort
            or {"open": "manual", "completed": "completed", "all": "newest"}[
                query.status
            ]
        ]
        with _cursor(self.profile_id, write=False) as (cursor, scope):
            if query.project is not None:
                name = _project_name(cursor, query.project)
                if name is not None:
                    predicates.append("p.name=%s")
                    values.append(name)
            where = " AND ".join(predicates)
            values = [scope.key, *values]
            cursor.execute(
                f"SELECT COUNT(*) AS total FROM {_PROJECT_ROWS} WHERE {where}", values
            )
            total = cursor.fetchone()["total"]
            cursor.execute(
                f"SELECT {scope.columns(detail=False)} FROM {_PROJECT_ROWS} WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s",
                (*values, query.limit, query.offset),
            )
            result = {
                "items": [_record(row) for row in cursor.fetchall()],
                "total": total,
            }
            if scope.profile_id is not None:
                result["profile_id"] = scope.profile_id
            return result

    def update(self, item_id: int, payload: Patch | dict) -> dict:
        item_id, patch = _id(item_id), Patch.model_validate(payload)
        self._validate_scope_fields(patch)
        changes = patch.model_dump(exclude_unset=True, exclude={"expected_revision"})
        with _cursor(self.profile_id, write=True) as (cursor, scope):
            before = _live(cursor, item_id, scope, patch.expected_revision)
            if "project" in changes:
                changes["project"] = _project_name(cursor, changes["project"])
            changes = {
                key: value for key, value in changes.items() if value != before[key]
            }
            if not changes:
                return _read(cursor, item_id, scope)
            if "project" in changes:
                project = _ensure_project(cursor, changes.pop("project"))
                changes["project_id"] = project["id"] if project else None
            if "status" in changes:
                if changes["status"] == "completed":
                    changes["sort_key"] = None
                    cursor.execute("SELECT clock_timestamp() AS completed_at")
                    changes["completed_at"] = cursor.fetchone()["completed_at"]
                else:
                    changes.update(
                        sort_key=_append_position(cursor, scope), completed_at=None
                    )
            columns = ", ".join(f"{key}=%s" for key in changes)
            cursor.execute(
                f"UPDATE action_items SET {columns},revision=revision+1,updated_at=clock_timestamp() WHERE id=%s AND scope_key=%s",
                (*changes.values(), item_id, scope.key),
            )
            if before["sort_key"] is not None and changes.get("status") == "completed":
                _compact(cursor, before["sort_key"], scope)
            return _read(cursor, item_id, scope)

    def delete(self, item_id: int, payload: Delete | dict) -> dict:
        item_id, request = _id(item_id), Delete.model_validate(payload)
        with _cursor(self.profile_id, write=True) as (cursor, scope):
            before = _live(cursor, item_id, scope, request.expected_revision)
            cursor.execute(
                "UPDATE action_items SET deleted_at=clock_timestamp(),sort_key=NULL,revision=revision+1,updated_at=clock_timestamp() WHERE id=%s AND scope_key=%s",
                (item_id, scope.key),
            )
            if before["sort_key"] is not None:
                _compact(cursor, before["sort_key"], scope)
            return {"deleted": True, "id": item_id}

    def move(self, item_id: int, payload: Move | dict) -> dict:
        item_id, request = _id(item_id), Move.model_validate(payload)
        anchor_id = (
            request.before_id if request.before_id is not None else request.after_id
        )
        if item_id == anchor_id:
            raise ValueError("The move anchor must be a different action item")
        with _cursor(self.profile_id, write=True) as (cursor, scope):
            source = _live(cursor, item_id, scope, request.expected_revision)
            cursor.execute(
                "SELECT sort_key FROM action_items WHERE id=%s AND scope_key=%s AND deleted_at IS NULL AND status='open' FOR UPDATE",
                (anchor_id, scope.key),
            )
            anchor = cursor.fetchone()
            if source["sort_key"] is None or anchor is None:
                raise Conflict(
                    "The source and move anchor must still be open. Refresh the list before moving again."
                )
            old, target = source["sort_key"], anchor["sort_key"]
            target += (1 if request.after_id is not None else 0) - (
                1 if old < target else 0
            )
            if target == old:
                return _read(cursor, item_id, scope)
            if target < old:
                cursor.execute(
                    "UPDATE action_items SET sort_key=sort_key+1 WHERE scope_key=%s AND sort_key>=%s AND sort_key<%s",
                    (scope.key, target, old),
                )
            else:
                cursor.execute(
                    "UPDATE action_items SET sort_key=sort_key-1 WHERE scope_key=%s AND sort_key>%s AND sort_key<=%s",
                    (scope.key, old, target),
                )
            cursor.execute(
                "UPDATE action_items SET sort_key=%s,revision=revision+1,updated_at=clock_timestamp() WHERE id=%s AND scope_key=%s",
                (target, item_id, scope.key),
            )
            return _read(cursor, item_id, scope)


def profile_queue(profile_id: str) -> Queue:
    if not isinstance(profile_id, str):
        raise ValueError("Discussion profile_id must be a UUID string")
    return Queue(profile_id)


def create(payload: Create | dict) -> dict:
    return Queue(None).create(payload)


def get(item_id: int) -> dict:
    return Queue(None).get(item_id)


def list_items(payload: Query | dict | None = None) -> dict:
    return Queue(None).list_items(payload)


def update(item_id: int, payload: Patch | dict) -> dict:
    return Queue(None).update(item_id, payload)


def delete(item_id: int, payload: Delete | dict) -> dict:
    return Queue(None).delete(item_id, payload)


def move(item_id: int, payload: Move | dict) -> dict:
    return Queue(None).move(item_id, payload)
