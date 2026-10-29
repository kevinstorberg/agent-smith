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


def list_terms() -> dict:
    with _cursor() as cur:
        cur.execute("SELECT * FROM meeting_vocabulary ORDER BY normalized_term, id")
        items = [_serialize(dict(row)) for row in cur.fetchall()]
        return {"items": items, "total": len(items)}


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
