from __future__ import annotations

from psycopg2 import sql

from services.api.models.base import BaseModel
from services.api.models.shared.listing import search_pattern, sort_clause
from services.db import get_connection

PROPOSAL_STATUSES = ("pending", "approved", "rejected")


def list_reviews(
    model: type[BaseModel],
    sorts: dict,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    *,
    q: str | None = None,
    sort: str = "newest",
) -> tuple[list[dict], int]:
    clauses, params = [], []
    if status:
        assert status in PROPOSAL_STATUSES, f"Invalid proposal status: {status}"
        clauses.append("status = %s")
        params.append(status)
    pattern = search_pattern(q)
    if pattern is not None:
        clauses.append("(title ILIKE %s OR target_name ILIKE %s)")
        params.extend([pattern, pattern])
    return model.list(
        where="WHERE " + " AND ".join(clauses) if clauses else "",
        params=tuple(params),
        order_by=sort_clause(sort, sorts),
        limit=limit,
        offset=offset,
    )


def count_reviews(model: type[BaseModel]) -> dict[str, int]:
    with get_connection() as conn, conn.cursor() as cursor:
        cursor.execute(
            sql.SQL("SELECT status, count(*) FROM {} GROUP BY status").format(
                sql.Identifier(model.table)
            )
        )
        counts = dict(cursor.fetchall())
    return {status: counts.get(status, 0) for status in PROPOSAL_STATUSES}
