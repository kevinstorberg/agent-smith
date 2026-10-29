from __future__ import annotations

from uuid import UUID

from services.meetings import stage_db
from services.meetings.db import _cursor, _serialize
from services.meetings.topics import normalize_topics


class MeetingLabelsNotFound(LookupError):
    pass


class MeetingLabelsConflict(RuntimeError):
    pass


def _revision(value: int, field: str = "expected_revision") -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")


def _snapshot(cur, meeting_id: str, *, lock: bool = False) -> dict:
    cur.execute("""SELECT id, revision, title, summary_text, project, labels, labels_revision, labels_source
        FROM meeting_summaries WHERE id = %s AND available""" + (" FOR UPDATE" if lock else ""), (str(UUID(meeting_id)),))
    row = cur.fetchone()
    if row is None:
        raise MeetingLabelsNotFound("Meeting no longer exists or is unavailable")
    return _serialize(dict(row))


def snapshot(meeting_id: str, expected_revision: int | None = None) -> dict:
    if expected_revision is not None:
        _revision(expected_revision)
    with _cursor() as cur:
        row = _snapshot(cur, meeting_id)
    if expected_revision is not None and row["labels_revision"] != expected_revision:
        raise MeetingLabelsConflict("Meeting labels changed; review the latest labels before trying again")
    return row


def public_labels(row: dict) -> dict:
    return {key: row[key] for key in ("labels", "labels_revision", "labels_source")}


def update(meeting_id: str, expected_revision: int, labels: list[str], expected_meeting_revision: int | None = None) -> dict:
    _revision(expected_revision)
    if expected_meeting_revision is not None:
        _revision(expected_meeting_revision, "expected_meeting_revision")
    labels = normalize_topics(labels)
    with _cursor() as cur:
        row = _snapshot(cur, meeting_id, lock=True)
        if row["labels_revision"] != expected_revision or (expected_meeting_revision is not None and row["revision"] != expected_meeting_revision):
            raise MeetingLabelsConflict("Meeting or labels changed; review the latest version before saving")
        if row["labels"] != labels or row["labels_source"] != "human":
            cur.execute("""UPDATE meeting_summaries SET labels = %s, labels_revision = labels_revision + 1,
                labels_source = 'human', updated_at = clock_timestamp() WHERE id = %s
                RETURNING labels, labels_revision, labels_source""", (labels, meeting_id))
            return dict(cur.fetchone())
        return public_labels(row)


def for_memories(meeting_ids: list[str]) -> dict[str, list[str]]:
    ids = list(dict.fromkeys(str(UUID(value)) for value in meeting_ids))
    if not ids:
        return {}
    with _cursor() as cur:
        cur.execute("SELECT id, labels FROM meeting_summaries WHERE available AND id IN %s", (tuple(ids),))
        return {str(row["id"]): normalize_topics(row["labels"]) for row in cur.fetchall()}


def apply_from_memory(meeting_id: str, owner: str, transcript_hash: str, meeting_revision: int,
                      expected_revision: int, labels: list[str]) -> str:
    _revision(meeting_revision, "meeting_revision")
    _revision(expected_revision)
    labels = normalize_topics(labels, allow_empty=False)
    with _cursor() as cur:
        stage_db.pending(cur, meeting_id, owner, transcript_hash, "memory")
        row = _snapshot(cur, meeting_id, lock=True)
        if row["labels_source"] == "human":
            return "human_owned"
        if row["revision"] != meeting_revision:
            return "stale_source"
        if row["labels_source"] == "agent" and row["labels"] == labels:
            return "unchanged"
        if row["labels_revision"] != expected_revision:
            return "stale_labels"
        cur.execute("""UPDATE meeting_summaries SET labels = %s, labels_revision = labels_revision + 1,
            labels_source = 'agent', updated_at = clock_timestamp() WHERE id = %s""", (labels, meeting_id))
        return "applied"
