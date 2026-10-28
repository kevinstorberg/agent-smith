from __future__ import annotations

import json
import random
from uuid import UUID

from psycopg2.extras import Json

from services.meetings.db import ClaimLostError, _cursor, _serialize
from services.meetings.digestion_db import _owned


def _pending(cur, meeting_id: str, owner: str, transcript_hash: str) -> dict:
    row = _owned(cur, meeting_id, owner)
    cur.execute("SELECT available FROM meeting_summaries WHERE id = %s FOR SHARE", (meeting_id,))
    meeting = cur.fetchone()
    if (not meeting or not meeting["available"] or row["transcript_status"] != "ready"
            or row["transcript_hash"] != transcript_hash or row["memory_status"] != "pending"):
        raise ClaimLostError("Meeting memory input changed or its stage is no longer pending")
    return row


def assert_publishable(meeting_id: str, owner: str, transcript_hash: str) -> None:
    with _cursor() as cur:
        _pending(cur, meeting_id, owner, transcript_hash)


def save_progress(meeting_id: str, owner: str, transcript_hash: str, artifact: dict, *, complete: bool = False) -> None:
    if not isinstance(artifact, dict) or len(json.dumps(artifact).encode()) > 2_000_000:
        raise ValueError("Meeting memory output must be an object of at most 2000000 bytes")
    with _cursor() as cur:
        _pending(cur, meeting_id, owner, transcript_hash)
        cur.execute(
            """UPDATE meeting_digestions SET memory_artifact = %s, memory_status = %s,
               memory_error = NULL, memory_updated_at = clock_timestamp(), updated_at = clock_timestamp()
               WHERE meeting_id = %s""", (Json(artifact), "done" if complete else "pending", meeting_id),
        )


def record_failure(meeting_id: str, owner: str, error_type: str) -> None:
    if not error_type or not error_type.replace("_", "").isalnum() or len(error_type) > 100:
        raise ValueError("Memory error must be a safe category")
    with _cursor() as cur:
        row = _owned(cur, meeting_id, owner)
        attempts = row["memory_attempts"] + 1
        delay = min(900, 60 * 5 ** (attempts - 1)) * random.uniform(0.8, 1.2)
        cur.execute(
            """UPDATE meeting_digestions SET memory_status = %s, memory_attempts = %s, memory_error = %s,
               memory_next_attempt_at = clock_timestamp() + %s * interval '1 second',
               memory_updated_at = clock_timestamp(), updated_at = clock_timestamp() WHERE meeting_id = %s""",
            ("failed" if attempts >= 3 else "pending", attempts, error_type, delay, meeting_id),
        )


def get_memories(meeting_id: str) -> dict | None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute(
            """SELECT d.meeting_id, d.transcript_status, d.memory_status, d.memory_artifact,
               d.memory_error, d.memory_updated_at, d.claim_until > clock_timestamp() AS running
               FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id = m.id
               WHERE m.id = %s AND m.available""", (meeting_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    status, reason, items = "not_imported", None, []
    if row["meeting_id"] is not None:
        status = row["memory_status"]
        if status == "done":
            items = row["memory_artifact"].get("items", [])
            reason = row["memory_artifact"].get("reason")
        elif row["transcript_status"] != "ready":
            status, reason = "blocked", "transcript_" + row["transcript_status"]
        elif row["running"]:
            status = "running"
    return _serialize({"status": status, "items": items, "reason": reason, "error_type": row["memory_error"], "updated_at": row["memory_updated_at"]})


def retry_memories(meeting_id: str) -> None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute(
            """UPDATE meeting_digestions SET memory_status = 'pending', memory_attempts = 0,
               memory_next_attempt_at = clock_timestamp(), memory_error = NULL, memory_updated_at = clock_timestamp()
               WHERE meeting_id = %s AND memory_status = 'failed' AND transcript_status = 'ready'""", (meeting_id,),
        )
        if cur.rowcount != 1:
            raise ValueError("Meeting memories cannot be retried in their current state")
