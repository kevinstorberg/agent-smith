from __future__ import annotations

from uuid import UUID
from datetime import datetime, timezone

from psycopg2.extras import Json

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
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (meeting_id,))
        row = cur.fetchone()
        if not row or row["memory_status"] != "failed" or row["transcript_status"] != "ready":
            raise ValueError("Meeting memories cannot be retried in their current state")
        cur.execute("SELECT * FROM meeting_summaries WHERE id=%s AND available FOR UPDATE", (meeting_id,))
        meeting = cur.fetchone()
        if not meeting:
            raise ValueError("Saved meeting is no longer available")
        restart_memory(cur, dict(row), dict(meeting), control=None)


def _publication_snapshot(cur, row: dict, meeting: dict) -> dict | None:
    from services.meetings import manual_analysis, manual_stage

    artifact = row.get("memory_artifact") or {}
    if not any(item["id"] not in artifact.get("published_ids", [])
               and item["id"] not in artifact.get("publication_envelopes", {}) for item in artifact.get("items", [])):
        return None
    if artifact.get("input_source") == "summary":
        snapshot = artifact.get("input_snapshot")
        if not isinstance(snapshot, dict):
            raise ValueError("Original summary publication context is unavailable")
        return snapshot
    marker = artifact.get("manual_request_id") or row.get("manual_analysis", {}).get("memory", {}).get("request_id")
    if marker:
        _, saved = manual_stage._receipt_stage(cur, row, "memory", marker)
        live = manual_analysis.expected_values(meeting, row)
        if any(live[key] != saved["source"][key] for key in manual_analysis.SOURCE_FIELDS):
            raise ValueError("Original memory publication context changed; uncertain publications cannot be reconstructed")
        return meeting
    return row.get("snapshot")


def restart_memory(cur, row: dict, meeting: dict, *, control: dict | None, capture_pending: bool = False,
                   request_reason: str = "memory_retry") -> None:
    from services.meetings import digestion_db, manual_analysis, memory_pass, work_requests
    from services.graphs.model_config import resolve_model_id

    capture_ready = row.get("transcript_status") == "ready"
    capture_retry = capture_pending and row.get("transcript_status") in {"pending", "failed", "unsupported", "unavailable"}
    if not (capture_ready or capture_retry) or not meeting.get("available"):
        raise ValueError("A saved meeting and completed capture are required to restart memories")
    if manual_analysis.has_active_lease(row):
        raise manual_analysis.AnalysisConflict("Meeting analysis is already running")
    snapshot = _serialize({key: meeting[key] for key in digestion_db._SNAPSHOT_FIELDS})
    created_at = datetime.now(timezone.utc).isoformat()
    retained = memory_pass.retained_artifact(row, created_at=created_at)
    publication_row = {**row, "memory_artifact": retained}
    artifact = memory_pass.restart_artifact(publication_row, snapshot, _publication_snapshot(cur, publication_row, meeting),
        created_at=created_at)
    artifact["model"] = resolve_model_id("meeting_memory", "curator")
    controls = dict(row.get("manual_analysis") or {})
    if control is None:
        controls.pop("memory", None)
    else:
        controls["memory"] = control
        artifact["manual_request_id"] = control["request_id"]
    stage_db.validate_artifact(artifact)
    cur.execute("""UPDATE meeting_digestions SET memory_status='pending',memory_artifact=%s,
        memory_attempts=0,memory_error=NULL,memory_next_attempt_at=clock_timestamp(),
        memory_updated_at=clock_timestamp(),updated_at=clock_timestamp(),requested_at=clock_timestamp(),
        claim_owner=NULL,claim_until=NULL,manual_analysis=%s WHERE meeting_id=%s""",
        (Json(artifact), Json(controls), row["meeting_id"]))
    work_requests.request(cur, row["meeting_id"], ("memory",), request_reason)
