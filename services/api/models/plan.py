from __future__ import annotations

import re

from psycopg2.extras import RealDictCursor

from scripts.shared.validation import assert_not_empty
from services.db import get_connection
from services.api.models.base import BaseModel
from services.api.models.shared.listing import (
    bidirectional_sorts,
    search_pattern,
    sort_clause,
)

PLAN_SORTS = {
    **bidirectional_sorts(
        {
            ("title", "title_desc"): ("lower(title)",),
            ("status_asc", "status_desc"): ("status",),
            ("project_asc", "project_desc"): ("NULLIF(lower(project), '')",),
            ("updated_asc", "updated"): ("updated_at",),
        }
    ),
    "newest": "created_at DESC, id DESC",
}

_METADATA_FIELDS = ("id", "title", "project", "status", "created_at", "updated_at")
SEARCH_EXCERPT_LENGTH = 600
SEARCH_MAX_QUERY_CHARS = 500
SEARCH_MAX_KEYWORDS = 10
SEARCH_MAX_PROJECT_CHARS = 200
SEARCH_MAX_LIMIT = 20
SEARCH_MAX_OFFSET = 10_000


def _scope_filters(project: str | None, status: str | None) -> tuple[list[str], list]:
    clauses, params = [], []
    for column, value in (("project", project), ("status", status)):
        if value:
            clauses.append(f"{column} = %s")
            params.append(value)
    return clauses, params


def _title_predicate(query: str) -> tuple[list[str], list]:
    assert_not_empty(query, "query")
    return ["title ILIKE %s"], [f"%{query}%"]


def _document_predicates(words: list[str]) -> tuple[list[str], list]:
    clauses, params = [], []
    for word in words:
        escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(title ILIKE %s OR body ILIKE %s)")
        params.extend([f"%{escaped}%"] * 2)
    return clauses, params


def _document_query(
    query: str, project: str | None, status: str | None, limit: int, offset: int
) -> list[str]:
    if (
        not isinstance(query, str)
        or not query.strip()
        or len(query.strip()) > SEARCH_MAX_QUERY_CHARS
    ):
        raise ValueError(
            f"query must contain 1-{SEARCH_MAX_QUERY_CHARS} nonblank characters after trimming"
        )
    words = query.split()
    if len(words) > SEARCH_MAX_KEYWORDS:
        raise ValueError(
            f"query must contain at most {SEARCH_MAX_KEYWORDS} whitespace-separated keywords"
        )
    if project is not None and (
        not isinstance(project, str)
        or len(project) > SEARCH_MAX_PROJECT_CHARS
        or project
        and not project.strip()
    ):
        raise ValueError(
            f"project must be empty or a nonblank string of at most {SEARCH_MAX_PROJECT_CHARS} characters"
        )
    if status not in (None, "", "draft", "final"):
        raise ValueError("status must be draft, final, or empty")
    if type(limit) is not int or not 1 <= limit <= SEARCH_MAX_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {SEARCH_MAX_LIMIT}")
    if type(offset) is not int or not 0 <= offset <= SEARCH_MAX_OFFSET:
        raise ValueError(f"offset must be an integer between 0 and {SEARCH_MAX_OFFSET}")
    return words


def _document_excerpt(body: str, words: list[str]) -> str:
    match = re.search(
        "|".join(re.escape(word) for word in words), body, flags=re.IGNORECASE
    )
    center = (match.start() + match.end()) // 2 if match else 0
    start = max(
        0, min(center - SEARCH_EXCERPT_LENGTH // 2, len(body) - SEARCH_EXCERPT_LENGTH)
    )
    return body[start : start + SEARCH_EXCERPT_LENGTH]


class PlanModel(BaseModel):
    table = "plans"

    @classmethod
    def create(
        cls,
        title: str,
        body: str,
        project: str | None = None,
        status: str = "final",
        conn=None,
    ) -> int:
        cls._validate_required({"title": title, "body": body}, ["title", "body"])
        return super().create(
            conn=conn, title=title, body=body, project=project, status=status
        )

    @classmethod
    def list(
        cls,
        project: str | None = None,
        status: str | None = None,
        limit: int | None = 10,
        offset: int = 0,
        *,
        q: str | None = None,
        sort: str = "updated",
    ) -> tuple[list[dict], int]:
        clauses, params = _scope_filters(project, status)
        pattern = search_pattern(q)
        if pattern is not None:
            clauses.append("title ILIKE %s")
            params.append(pattern)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return super().list(
            columns=", ".join(_METADATA_FIELDS),
            where=where,
            params=tuple(params),
            limit=limit,
            offset=offset,
            order_by=sort_clause(sort, PLAN_SORTS),
        )

    @classmethod
    def update(
        cls,
        plan_id: int,
        title: str | None = None,
        body: str | None = None,
        project: str | None = "UNSET",
    ) -> None:
        fields = cls._collect_fields(title=title, body=body)
        if project != "UNSET":
            fields["project"] = project or None
        if fields:
            cls.dynamic_update(plan_id, fields)

    @classmethod
    def search(
        cls,
        query: str,
        project: str | None = None,
        limit: int = 100,
        *,
        status: str | None = None,
    ) -> list[dict]:
        clauses, params = _title_predicate(query)
        return cls._search_rows(clauses, params, project, status, limit)

    @classmethod
    def search_documents(
        cls,
        query: str,
        project: str | None = None,
        status: str | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> dict:
        words = _document_query(query, project, status, limit, offset)
        clauses, params = _document_predicates(words)
        rows = cls._search_rows(
            clauses,
            params,
            project,
            status,
            limit + 1,
            offset,
            order_by="updated_at DESC, id DESC",
        )
        has_more = len(rows) > limit
        pagination_capped = has_more and offset + limit > SEARCH_MAX_OFFSET
        return {
            "items": [
                {
                    **{key: row[key] for key in _METADATA_FIELDS},
                    "excerpt": _document_excerpt(row["body"], words),
                }
                for row in rows[:limit]
            ],
            "has_more": has_more,
            "next_offset": offset + limit
            if has_more and not pagination_capped
            else None,
            "pagination_capped": pagination_capped,
        }

    @classmethod
    def _search_rows(
        cls,
        clauses: list[str],
        params: list,
        project: str | None,
        status: str | None,
        limit: int,
        offset: int = 0,
        *,
        order_by: str = "updated_at DESC",
    ) -> list[dict]:
        scope_clauses, scope_params = _scope_filters(project, status)
        where = " AND ".join([*clauses, *scope_clauses])
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SET LOCAL statement_timeout = '5s'")
                cur.execute(
                    f"SELECT * FROM {cls.table} WHERE {where} ORDER BY {order_by} LIMIT %s OFFSET %s",
                    (*params, *scope_params, limit, offset),
                )
                return [cls.serialize_timestamps(r) for r in cur.fetchall()]


list_plans = PlanModel.list
search_plans = PlanModel.search
search_documents = PlanModel.search_documents
get_plan = PlanModel.read
create_plan = PlanModel.create
update_plan = PlanModel.update
delete_plan = PlanModel.destroy
