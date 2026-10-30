from __future__ import annotations

from uuid import UUID

from services.meetings import stage_db, stage_state
from services.meetings.db import _cursor, _serialize


def _pending(cur, meeting_id: str, owner: str, transcript_hash: str) -> dict:
    return stage_db.pending(cur, meeting_id, owner, transcript_hash, "memory")


def assert_publishable(meeting_id: str, owner: str, transcript_hash: str) -> None:
    with _cursor() as cur:
        _pending(cur, meeting_id, owner, transcript_hash)


def save_progress(meeting_id: str, owner: str, transcript_hash: str, artifact: dict, *, complete: bool = False) -> None:
    stage_db.save_progress("memory", meeting_id, owner, transcript_hash, artifact, complete=complete)


def record_failure(meeting_id: str, owner: str, error_type: str) -> None:
    stage_db.record_failure("memory", meeting_id, owner, error_type)


def get_memories(meeting_id: str) -> dict | None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute(
            f"""SELECT d.meeting_id, d.transcript_status, d.memory_status, d.memory_artifact,
               d.memory_attempts, d.memory_next_attempt_at, {stage_db.TOTAL_UNITS_SQL} AS total_units,
               d.memory_error, d.memory_updated_at, d.claim_until > clock_timestamp() AS running
               FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id = m.id
               WHERE m.id = %s AND m.available""", (meeting_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    state = stage_state.generation(dict(row), "memory")
    items = row["memory_artifact"].get("items", []) if state["status"] == "done" else []
    return _serialize({**state, "items": items, "updated_at": row["memory_updated_at"]})


def retry_memories(meeting_id: str) -> None:
    from services.meetings import manual_stage

    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (meeting_id,))
        row = cur.fetchone()
        if row and manual_stage.resume_stage(cur, dict(row), "memory"):
            return
        cur.execute(
            """UPDATE meeting_digestions SET memory_status = 'pending', memory_attempts = 0,
               memory_next_attempt_at = clock_timestamp(), memory_error = NULL, memory_updated_at = clock_timestamp(),
               requested_at = coalesce(requested_at, clock_timestamp())
               WHERE meeting_id = %s AND memory_status = 'failed' AND transcript_status = 'ready'""", (meeting_id,),
        )
        if cur.rowcount != 1:
            raise ValueError("Meeting memories cannot be retried in their current state")
