from __future__ import annotations

import json
import random

from psycopg2.extras import Json

from services.meetings.db import ClaimLostError, _cursor
from services.meetings.digestion_db import _owned
from services.meetings.windows import WINDOW_CHARS

TOTAL_UNITS_SQL = f"(SELECT sum(greatest(1, (char_length(segment->>'text') + {WINDOW_CHARS - 1}) / {WINDOW_CHARS})) FROM jsonb_array_elements(d.transcript->'segments') segment)"


def progress(row: dict | None, stage: str, *, total_units: int | None = None) -> dict:
    stage = _stage(stage)
    row = row or {}
    artifact = row.get(stage + "_artifact") or {}
    return {
        "processed_units": artifact.get("offset", 0), "total_units": artifact.get("total_units", total_units),
        "staged_count": len(artifact.get("draft_assignments", [])) if stage == "speaker" else len(artifact.get("items", [])) + (len(artifact.get("metadata_updates", [])) if stage == "profile" else 0),
        "saved_count": sum(item.get("confidence") == "high" for item in artifact.get("assignments", [])) if stage == "speaker"
        else len(artifact.get("published_ids" if stage == "memory" else "profile_ids", [])),
        "attempts": row.get(stage + "_attempts", 0), "next_attempt_at": row.get(stage + "_next_attempt_at"),
    }


def _stage(stage: str) -> str:
    if stage not in {"memory", "profile", "speaker"}:
        raise ValueError("Unknown meeting stage")
    return stage


def pending(cur, meeting_id: str, owner: str, transcript_hash: str, stage: str) -> dict:
    stage = _stage(stage)
    row = _owned(cur, meeting_id, owner, profile=stage == "profile")
    cur.execute("SELECT available FROM meeting_summaries WHERE id = %s FOR SHARE", (meeting_id,))
    meeting = cur.fetchone()
    if (not meeting or not meeting["available"] or row["transcript_status"] != "ready"
            or row["transcript_hash"] != transcript_hash or row[stage + "_status"] != "pending"):
        raise ClaimLostError("Meeting stage input changed or its prerequisites are no longer satisfied")
    return row


def validate_artifact(artifact: dict) -> None:
    if not isinstance(artifact, dict) or len(json.dumps(artifact).encode()) > 2_000_000:
        raise ValueError("Meeting stage output must be an object of at most 2000000 bytes")


def save_progress(stage: str, meeting_id: str, owner: str, transcript_hash: str, artifact: dict, *, complete: bool = False) -> None:
    stage = _stage(stage)
    validate_artifact(artifact)
    with _cursor() as cur:
        pending(cur, meeting_id, owner, transcript_hash, stage)
        write_progress(cur, stage, meeting_id, artifact, complete=complete)


def write_progress(cur, stage: str, meeting_id: str, artifact: dict, *, complete: bool = False) -> None:
    stage = _stage(stage)
    cur.execute(
        f"""UPDATE meeting_digestions SET {stage}_artifact = %s, {stage}_status = %s,
           {stage}_error = NULL, {stage}_updated_at = clock_timestamp(), updated_at = clock_timestamp()
           WHERE meeting_id = %s""", (Json(artifact), "done" if complete else "pending", meeting_id),
    )


def record_failure(stage: str, meeting_id: str, owner: str, error_type: str) -> None:
    stage = _stage(stage)
    if not isinstance(error_type, str) or not error_type or not error_type.replace("_", "").isalnum() or len(error_type) > 100:
        raise ValueError("Meeting stage error must be a safe category")
    with _cursor() as cur:
        row = _owned(cur, meeting_id, owner, profile=stage == "profile")
        attempts = row[stage + "_attempts"] + 1
        delay = min(900, 60 * 5 ** (attempts - 1)) * random.uniform(0.8, 1.2)
        cur.execute(
            f"""UPDATE meeting_digestions SET {stage}_status = %s, {stage}_attempts = %s, {stage}_error = %s,
               {stage}_next_attempt_at = clock_timestamp() + %s * interval '1 second',
               {stage}_updated_at = clock_timestamp(), updated_at = clock_timestamp() WHERE meeting_id = %s""",
            ("failed" if attempts >= 3 else "pending", attempts, error_type, delay, meeting_id),
        )
