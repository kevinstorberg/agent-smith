from __future__ import annotations

import json
import re
from uuid import UUID

from services.meetings.db import _cursor, _serialize
from services.meetings.profile_fields import text

MAX_TERMS = 100
MAX_CONTEXT_CHARS = 16_000


class VocabularyConflictError(RuntimeError):
    pass


class VocabularyContextTooLargeError(ValueError):
    pass


def _term(value: str) -> str:
    result = " ".join(text(value, "Vocabulary term", 200).split())
    if not result:
        raise ValueError("Vocabulary term must be nonblank")
    return result


def _revision(value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("Expected vocabulary revision must be a positive integer")


def list_terms(*, query: str | None = None, limit: int | None = None, offset: int = 0) -> dict:
    if query is not None and (not isinstance(query, str) or len(query) > 1000):
        raise ValueError("Vocabulary query must contain at most 1000 characters")
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 100):
        raise ValueError("Vocabulary limit must be an integer from 1 to 100")
    if type(offset) is not int or offset < 0:
        raise ValueError("Vocabulary offset must be a nonnegative integer")
    query = " ".join((query or "").casefold().split())
    with _cursor() as cur:
        cur.execute("""WITH matching AS (
            SELECT * FROM meeting_vocabulary WHERE %s='' OR strpos(normalized_term,%s)>0 OR strpos(lower(definition),%s)>0
        ), page AS (
            SELECT * FROM matching ORDER BY normalized_term,id LIMIT %s OFFSET %s
        ) SELECT totals.total,page.*
          FROM (SELECT count(*) AS total FROM matching) totals LEFT JOIN page ON true
          ORDER BY page.normalized_term,page.id""", (query, query, query, limit, offset))
        rows = cur.fetchall()
        return {"items": [_serialize({key: value for key, value in row.items() if key != "total"}) for row in rows if row["id"] is not None], "total": rows[0]["total"]}


def get_term(term_id: str) -> dict | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM meeting_vocabulary WHERE id=%s", (str(UUID(term_id)),))
        row = cur.fetchone()
        return _serialize(dict(row)) if row else None


def create(term: str, definition: str = "") -> dict:
    term, definition = _term(term), text(definition, "Vocabulary definition", 2000)
    with _cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('agent-smith:vocabulary', 0))")
        cur.execute("SELECT count(*) AS count FROM meeting_vocabulary")
        if cur.fetchone()["count"] >= MAX_TERMS:
            raise ValueError(f"Meeting vocabulary supports at most {MAX_TERMS} terms")
        cur.execute("""INSERT INTO meeting_vocabulary (term, normalized_term, definition)
            VALUES (%s, %s, %s) ON CONFLICT (normalized_term) DO NOTHING RETURNING *""",
                    (term, term.casefold(), definition))
        row = cur.fetchone()
        if row is None:
            raise VocabularyConflictError("This term already exists; edit its definition instead")
        return _serialize(dict(row))


def update(term_id: str, expected_revision: int, term: str, definition: str = "") -> dict:
    key = str(UUID(term_id))
    _revision(expected_revision)
    term, definition = _term(term), text(definition, "Vocabulary definition", 2000)
    with _cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('agent-smith:vocabulary', 0))")
        cur.execute("SELECT * FROM meeting_vocabulary WHERE id = %s FOR UPDATE", (key,))
        row = cur.fetchone()
        if row is None:
            raise LookupError("Vocabulary term not found")
        if row["revision"] != expected_revision:
            raise VocabularyConflictError("This term changed; refresh before saving")
        cur.execute("SELECT 1 FROM meeting_vocabulary WHERE normalized_term = %s AND id <> %s", (term.casefold(), key))
        if cur.fetchone():
            raise VocabularyConflictError("Another term already uses this spelling")
        if row["term"] == term and row["definition"] == definition:
            return _serialize(dict(row))
        cur.execute("""UPDATE meeting_vocabulary SET term = %s, normalized_term = %s, definition = %s,
            revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s RETURNING *""",
                    (term, term.casefold(), definition, key))
        return _serialize(dict(cur.fetchone()))


def delete(term_id: str, expected_revision: int) -> None:
    _revision(expected_revision)
    with _cursor() as cur:
        cur.execute("DELETE FROM meeting_vocabulary WHERE id = %s AND revision = %s RETURNING id", (str(UUID(term_id)), expected_revision))
        if cur.fetchone() is None:
            raise VocabularyConflictError("This term changed or was removed; refresh before deleting")


def relevant(content: str) -> list[dict]:
    if not isinstance(content, str):
        raise ValueError("Vocabulary matching requires text")
    normalized = " ".join(content.casefold().split())
    selected = [{"term": item["term"], "definition": item["definition"]} for item in list_terms()["items"]
                if re.search(r"(?<!\w)" + re.escape(item["normalized_term"]) + r"(?!\w)", normalized)]
    if len(json.dumps(selected, ensure_ascii=False)) > MAX_CONTEXT_CHARS:
        raise VocabularyContextTooLargeError("Relevant meeting vocabulary exceeds the analysis context limit; shorten its definitions")
    return selected
