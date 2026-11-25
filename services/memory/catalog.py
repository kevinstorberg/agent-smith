from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator, TypeVar
from uuid import UUID, uuid4

import psycopg2
from psycopg2.errors import UniqueViolation
from psycopg2.extras import Json, RealDictCursor, execute_values

from services.api.models.shared.listing import sort_clause
from services.db import get_connection
from services.meetings.topics import normalize_topics
from services.memory.backends import metadata_datetime


class Unavailable(RuntimeError):
    pass


class Conflict(RuntimeError):
    pass


class NoWritePerformed(KeyError):
    """Only raise after proving that no provider mutation was attempted."""


@dataclass(frozen=True)
class Source:
    index_name: str
    namespace: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.index_name, str) or not self.index_name.strip():
            raise ValueError("Memory catalog index name must be nonblank text")
        if not isinstance(self.namespace, str):
            raise ValueError("Memory catalog namespace must be text")
        if self.namespace == "__default__":
            object.__setattr__(self, "namespace", "")

    @property
    def key(self) -> str:
        return json.dumps(
            ["pinecone", self.index_name, self.namespace], separators=(",", ":")
        )


@dataclass(frozen=True)
class Page:
    ids: list[str]
    context_tags: dict[str, list[str]]
    total: int
    generation: int


_SORTS = {
    "created_at_asc": "created_at ASC NULLS FIRST, id ASC",
    "created_at_desc": "created_at DESC NULLS LAST, id ASC",
    "updated_at_asc": "updated_at ASC NULLS FIRST, id ASC",
    "updated_at_desc": "updated_at DESC NULLS LAST, id ASC",
}
_STATE = """SELECT s.*, EXISTS(SELECT 1 FROM memory_catalog_pending p
    WHERE p.source_key=s.source_key) AS dirty
    FROM memory_catalog_sources s WHERE s.source_key=%s"""


@contextmanager
def _cursor() -> Iterator[RealDictCursor]:
    try:
        with (
            get_connection() as connection,
            connection.cursor(cursor_factory=RealDictCursor) as cursor,
        ):
            cursor.execute("SET LOCAL statement_timeout='5s'")
            cursor.execute("SET LOCAL lock_timeout='1s'")
            yield cursor
    except UniqueViolation:
        raise Conflict(
            "Memory catalog operation conflicts with an existing pending operation or staged ID"
        ) from None
    except psycopg2.Error as error:
        raise Unavailable(
            f"Memory listing storage failed (SQLSTATE {error.pgcode or 'unknown'})"
        ) from None


def _require_ready(row) -> None:
    if row is None or row.get("status") is None or row["status"] == "empty":
        raise Unavailable(
            "Memory listing index is not initialized; explicit initialization is required"
        )
    if row["status"] != "ready":
        raise Unavailable(
            f"Memory listing index is {row['status']}; explicit maintenance is required"
        )
    if row["dirty"]:
        raise Unavailable(
            "Memory listing index has unresolved writes; explicit known-ID repair is required"
        )


def select_page(
    source: Source,
    *,
    repo: str | None = None,
    tags: list[str] | None = None,
    sort: str = "created_at_desc",
    limit: int = 20,
    offset: int = 0,
    meeting_only: bool = False,
    changed_after: datetime | None = None,
) -> Page:
    if not isinstance(source, Source):
        raise ValueError("Memory catalog source must be a Source")
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or type(offset) is not int
        or offset < 0
    ):
        raise ValueError("Memory page requires limit 1-100 and nonnegative offset")
    if repo is not None and (not isinstance(repo, str) or repo and not repo.strip()):
        raise ValueError("Memory repository must be nonblank text or null")
    repo = repo or None
    if tags is not None and (
        not isinstance(tags, list)
        or any(not isinstance(tag, str) or not tag.strip() for tag in tags)
    ):
        raise ValueError("Memory tags must be a list of nonblank strings")
    if type(meeting_only) is not bool:
        raise ValueError("meeting_only must be boolean")
    if changed_after is not None:
        if not isinstance(changed_after, datetime) or changed_after.utcoffset() is None:
            raise ValueError("Memory lookback must be a timezone-aware datetime")
        changed_after = changed_after.astimezone(timezone.utc)
    order = sort_clause(sort, _SORTS)
    with _cursor() as cursor:
        cursor.execute(
            f"""WITH state AS ({_STATE}), filtered AS MATERIALIZED (
                SELECT e.id,e.created_at,e.updated_at,COALESCE(m.labels,'{{}}'::text[]) AS context_tags
                FROM memory_catalog_entries e
                JOIN state s ON s.status='ready' AND NOT s.dirty AND e.catalog_version=s.active_version
                LEFT JOIN meeting_summaries m ON e.meeting_id=m.id AND m.available
                WHERE e.source_key=%s AND (%s IS NULL OR e.repo=%s)
                  AND (NOT %s OR e.source_type='meeting')
                  AND %s::text[] <@ (e.tags || COALESCE(m.labels,'{{}}'::text[]))
                  AND (%s::timestamptz IS NULL OR COALESCE(e.updated_at,e.created_at)>=%s::timestamptz)
            ), selected AS (SELECT * FROM filtered ORDER BY {order} LIMIT %s OFFSET %s)
            SELECT (SELECT status FROM state) AS status,
                   (SELECT generation FROM state) AS generation,
                   (SELECT dirty FROM state) AS dirty,
                   (SELECT count(*) FROM filtered) AS total,
                   COALESCE((SELECT jsonb_agg(jsonb_build_object('id',id,'context_tags',context_tags) ORDER BY {order})
                             FROM selected),'[]'::jsonb) AS items""",
            (
                source.key,
                source.key,
                repo,
                repo,
                meeting_only,
                tags or [],
                changed_after,
                changed_after,
                limit,
                offset,
            ),
        )
        row = cursor.fetchone()
    _require_ready(row)
    items = row["items"]
    if len(items) > limit:
        raise Unavailable("Memory listing index returned more IDs than requested")
    return Page(
        ids=[item["id"] for item in items],
        context_tags={
            item["id"]: normalize_topics(item["context_tags"]) for item in items
        },
        total=row["total"],
        generation=row["generation"],
    )


def check_page(source: Source, generation: int) -> None:
    if not isinstance(source, Source) or type(generation) is not int or generation < 0:
        raise ValueError(
            "Memory page validation requires a source and nonnegative generation"
        )
    with _cursor() as cursor:
        cursor.execute(_STATE, (source.key,))
        row = cursor.fetchone()
    _require_ready(row)
    if row["generation"] != generation:
        raise Unavailable(
            "Memory listing changed while its page was fetched; refresh before continuing"
        )


@dataclass(frozen=True)
class Mutation:
    source: Source
    id: str
    token: str
    kind: str
    phase: str = "pending"

    @property
    def acknowledged(self) -> bool:
        return self.phase == "acknowledged"


@dataclass(frozen=True)
class Build:
    source: Source
    token: str
    version: int
    expected_count: int


_ENTRY_FIELDS = (
    "id",
    "repo",
    "tags",
    "source_type",
    "source_id",
    "meeting_id",
    "created_at",
    "updated_at",
)
_T = TypeVar("_T")


def _id(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Memory catalog ID must be a UUID") from None


def _projection(metadata: dict, id: str) -> dict:
    if not isinstance(metadata, dict) or _id(metadata.get("id")) != id:
        raise ValueError("Memory catalog projection must identify the mutated memory")
    for field in ("repo", "source_type", "source_id"):
        if metadata.get(field) is not None and not isinstance(metadata[field], str):
            raise ValueError(f"Memory catalog {field} must be text or null")
    tags = metadata.get("tags") or []
    if not isinstance(tags, list) or any(
        not isinstance(tag, str) or not tag.strip() for tag in tags
    ):
        raise ValueError("Memory catalog tags must be nonblank strings")
    meeting_id = None
    if metadata.get("source_type") == "meeting":
        try:
            meeting_id = str(UUID(metadata.get("source_id")))
        except (ValueError, TypeError, AttributeError):
            pass
    return {
        "id": id,
        "repo": metadata.get("repo") or None,
        "tags": list(tags),
        "source_type": metadata.get("source_type"),
        "source_id": metadata.get("source_id"),
        "meeting_id": meeting_id,
        **{
            field: metadata_datetime(metadata[field], field).isoformat()
            if metadata.get(field) is not None
            else None
            for field in ("created_at", "updated_at")
        },
    }


def _locked_source(cursor, source: Source, *, create: bool = False):
    if not isinstance(source, Source):
        raise ValueError("Memory catalog source must be a Source")
    if create:
        cursor.execute(
            "INSERT INTO memory_catalog_sources(source_key) VALUES(%s) ON CONFLICT DO NOTHING",
            (source.key,),
        )
    cursor.execute(
        "SELECT * FROM memory_catalog_sources WHERE source_key=%s FOR UPDATE",
        (source.key,),
    )
    row = cursor.fetchone()
    if row is None:
        raise Unavailable("Memory listing source has not been initialized")
    return row


def _entry(cursor, source: Source, version: int, projection: dict) -> None:
    columns = ",".join(_ENTRY_FIELDS)
    updates = ",".join(
        f"{field}=EXCLUDED.{field}" for field in _ENTRY_FIELDS if field != "id"
    )
    cursor.execute(
        f"INSERT INTO memory_catalog_entries(source_key,catalog_version,{columns}) VALUES({','.join(['%s'] * 10)}) "
        f"ON CONFLICT(source_key,catalog_version,id) DO UPDATE SET {updates}",
        (source.key, version, *(projection[field] for field in _ENTRY_FIELDS)),
    )


def _new_pending(cursor, source: Source, id: str, kind: str) -> Mutation:
    mutation = Mutation(source, id, str(uuid4()), kind)
    cursor.execute(
        """INSERT INTO memory_catalog_pending(source_key,id,operation_token,kind)
        VALUES(%s,%s,%s,%s)""",
        (source.key, id, mutation.token, kind),
    )
    cursor.execute(
        "UPDATE memory_catalog_sources SET generation=generation+1 WHERE source_key=%s",
        (source.key,),
    )
    return mutation


def begin_mutation(source: Source, id: str, *, kind: str) -> Mutation:
    id = _id(id)
    if kind not in {"upsert", "delete"}:
        raise ValueError("Memory mutation kind must be upsert or delete")
    with _cursor() as cursor:
        state = _locked_source(cursor, source, create=True)
        if state["status"] == "building":
            raise Unavailable(
                "Memory metadata writes are blocked while explicit initialization is building"
            )
        return _new_pending(cursor, source, id, kind)


def _pending(cursor, mutation: Mutation):
    cursor.execute(
        "SELECT * FROM memory_catalog_pending WHERE source_key=%s AND id=%s FOR UPDATE",
        (mutation.source.key, mutation.id),
    )
    row = cursor.fetchone()
    if row is not None and str(row["operation_token"]) != mutation.token:
        raise Conflict(
            "Memory mutation token changed; an older operation cannot finalize it"
        )
    return row


def acknowledge(mutation: Mutation, metadata: dict | None) -> None:
    projection = _projection(metadata, mutation.id) if metadata is not None else None
    with _cursor() as cursor:
        _locked_source(cursor, mutation.source)
        row = _pending(cursor, mutation)
        if row is None:
            return
        if row["phase"] == "acknowledged":
            if row["projection"] != projection:
                raise Conflict(
                    "Memory mutation was already acknowledged with different metadata"
                )
            return
        cursor.execute(
            """UPDATE memory_catalog_pending SET phase='acknowledged',kind=%s,projection=%s
            WHERE source_key=%s AND id=%s AND operation_token=%s""",
            (
                "upsert" if projection is not None else "delete",
                Json(projection) if projection is not None else None,
                mutation.source.key,
                mutation.id,
                mutation.token,
            ),
        )


def finalize(mutation: Mutation) -> None:
    with _cursor() as cursor:
        state = _locked_source(cursor, mutation.source)
        row = _pending(cursor, mutation)
        if row is None:
            return
        if row["phase"] != "acknowledged":
            raise Conflict("Memory mutation has not acknowledged provider success")
        if row["kind"] == "delete":
            cursor.execute(
                "DELETE FROM memory_catalog_entries WHERE source_key=%s AND id=%s",
                (mutation.source.key, mutation.id),
            )
        else:
            _entry(cursor, mutation.source, state["active_version"], row["projection"])
        cursor.execute(
            "DELETE FROM memory_catalog_pending WHERE source_key=%s AND id=%s AND operation_token=%s",
            (mutation.source.key, mutation.id, mutation.token),
        )
        cursor.execute(
            "UPDATE memory_catalog_sources SET generation=generation+1 WHERE source_key=%s",
            (mutation.source.key,),
        )


def write_through(
    source: Source,
    id: str,
    *,
    kind: str,
    metadata: dict | None,
    operation: Callable[[], _T],
) -> _T:
    id = _id(id)
    if not callable(operation):
        raise ValueError("Memory provider operation must be callable")
    if (kind == "upsert") != (metadata is not None):
        raise ValueError("Upserts require metadata; deletes must not include metadata")
    projection = _projection(metadata, id) if metadata is not None else None
    mutation = begin_mutation(source, id, kind=kind)
    try:
        result = operation()
    except NoWritePerformed:
        if kind == "delete":
            acknowledge(mutation, None)
            finalize(mutation)
        else:
            cancel_unstarted(mutation)
        raise
    acknowledge(mutation, projection)
    finalize(mutation)
    return result


def pending(source: Source) -> list[Mutation]:
    with _cursor() as cursor:
        cursor.execute(
            "SELECT id,operation_token,kind,phase FROM memory_catalog_pending WHERE source_key=%s ORDER BY id",
            (source.key,),
        )
        return [
            Mutation(
                source,
                str(row["id"]),
                str(row["operation_token"]),
                row["kind"],
                row["phase"],
            )
            for row in cursor.fetchall()
        ]


def cancel_unstarted(mutation: Mutation) -> None:
    with _cursor() as cursor:
        _locked_source(cursor, mutation.source)
        row = _pending(cursor, mutation)
        if row is None:
            return
        if row["phase"] != "pending":
            raise Conflict("An acknowledged provider mutation cannot be canceled")
        cursor.execute(
            "DELETE FROM memory_catalog_pending WHERE source_key=%s AND id=%s AND operation_token=%s",
            (mutation.source.key, mutation.id, mutation.token),
        )
        cursor.execute(
            "UPDATE memory_catalog_sources SET generation=generation+1 WHERE source_key=%s",
            (mutation.source.key,),
        )


def claim_repair(source: Source, id: str, *, quiescent: bool) -> Mutation:
    id = _id(id)
    if quiescent is not True:
        raise ValueError(
            "Known-ID repair requires confirmation that provider writers are quiescent"
        )
    with _cursor() as cursor:
        state = _locked_source(cursor, source)
        if state["status"] == "building":
            raise Unavailable(
                "Memory repair is blocked while initialization is building"
            )
        cursor.execute(
            "SELECT * FROM memory_catalog_pending WHERE source_key=%s AND id=%s FOR UPDATE",
            (source.key, id),
        )
        row = cursor.fetchone()
        if row is None:
            return _new_pending(cursor, source, id, "upsert")
        if row["phase"] == "acknowledged":
            return Mutation(
                source, id, str(row["operation_token"]), row["kind"], row["phase"]
            )
        token = str(uuid4())
        cursor.execute(
            "UPDATE memory_catalog_pending SET operation_token=%s,started_at=clock_timestamp() WHERE source_key=%s AND id=%s",
            (token, source.key, id),
        )
        cursor.execute(
            "UPDATE memory_catalog_sources SET generation=generation+1 WHERE source_key=%s",
            (source.key,),
        )
        return Mutation(source, id, token, row["kind"])


def begin_build(source: Source, *, expected_count: int) -> Build:
    if type(expected_count) is not int or expected_count < 0:
        raise ValueError("Expected memory count must be nonnegative")
    with _cursor() as cursor:
        state = _locked_source(cursor, source, create=True)
        cursor.execute(
            "SELECT EXISTS(SELECT 1 FROM memory_catalog_pending WHERE source_key=%s) AS dirty",
            (source.key,),
        )
        if cursor.fetchone()["dirty"] or state["status"] == "building":
            raise Conflict(
                "Initialization requires no pending writes and no active build"
            )
        build = Build(source, str(uuid4()), state["generation"] + 1, expected_count)
        cursor.execute(
            "DELETE FROM memory_catalog_entries WHERE source_key=%s AND catalog_version<>%s",
            (source.key, state["active_version"]),
        )
        cursor.execute(
            """UPDATE memory_catalog_sources SET status='building',generation=%s,build_version=%s,
            build_token=%s,build_expected_count=%s WHERE source_key=%s""",
            (build.version, build.version, build.token, expected_count, source.key),
        )
        return build


def _building(cursor, build: Build):
    state = _locked_source(cursor, build.source)
    if (
        state["status"] != "building"
        or str(state["build_token"]) != build.token
        or state["build_version"] != build.version
        or state["build_expected_count"] != build.expected_count
    ):
        raise Conflict("Memory initialization ownership changed")
    return state


def stage_build(build: Build, projected_rows: list[dict]) -> None:
    rows = [_projection(row, _id(row.get("id"))) for row in projected_rows]
    if len({row["id"] for row in rows}) != len(rows):
        raise Conflict("Memory initialization batch contains duplicate IDs")
    with _cursor() as cursor:
        _building(cursor, build)
        cursor.execute(
            "SELECT count(*) AS count FROM memory_catalog_entries WHERE source_key=%s AND catalog_version=%s",
            (build.source.key, build.version),
        )
        if cursor.fetchone()["count"] + len(rows) > build.expected_count:
            raise Conflict("Memory initialization exceeded the approved expected count")
        if rows:
            execute_values(
                cursor,
                f"INSERT INTO memory_catalog_entries(source_key,catalog_version,{','.join(_ENTRY_FIELDS)}) VALUES %s",
                [
                    (
                        build.source.key,
                        build.version,
                        *(row[field] for field in _ENTRY_FIELDS),
                    )
                    for row in rows
                ],
            )


def finish_build(build: Build) -> int:
    with _cursor() as cursor:
        _building(cursor, build)
        cursor.execute(
            "SELECT count(*) AS count FROM memory_catalog_entries WHERE source_key=%s AND catalog_version=%s",
            (build.source.key, build.version),
        )
        count = cursor.fetchone()["count"]
        if count != build.expected_count:
            raise Conflict(
                "Memory initialization count differs from the approved expected count"
            )
        cursor.execute(
            """UPDATE memory_catalog_sources SET status='ready',active_version=%s,generation=generation+1,
            build_version=NULL,build_token=NULL,build_expected_count=NULL,initialized_at=clock_timestamp() WHERE source_key=%s""",
            (build.version, build.source.key),
        )
        cursor.execute(
            "DELETE FROM memory_catalog_entries WHERE source_key=%s AND catalog_version<>%s",
            (build.source.key, build.version),
        )
        return count


def fail_build(build: Build) -> None:
    with _cursor() as cursor:
        cursor.execute(
            """UPDATE memory_catalog_sources SET status='failed',generation=generation+1,
            build_version=NULL,build_token=NULL,build_expected_count=NULL
            WHERE source_key=%s AND status='building' AND build_token=%s""",
            (build.source.key, build.token),
        )


def abort_build(source: Source, *, quiescent: bool) -> bool:
    if quiescent is not True:
        raise ValueError(
            "Aborting initialization requires confirmation that its worker has stopped"
        )
    with _cursor() as cursor:
        state = _locked_source(cursor, source)
        if state["status"] != "building":
            return False
        cursor.execute(
            """UPDATE memory_catalog_sources SET status='failed',generation=generation+1,
            build_version=NULL,build_token=NULL,build_expected_count=NULL WHERE source_key=%s""",
            (source.key,),
        )
        return True
