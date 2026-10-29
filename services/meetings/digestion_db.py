from __future__ import annotations

import hashlib
import json
import random
from uuid import UUID

from psycopg2.extras import Json

from services.meetings.db import ClaimLostError, _cursor, _serialize

LEASE_SECONDS = 600
_CLAIM_LOCK = "agent-smith:meeting-digestion"
_SNAPSHOT_FIELDS = (
    "id", "provider", "account_key", "external_id", "source_name", "project", "title",
    "summary_text", "source_url", "metadata", "provider_updated_at", "revision",
)


def enroll(cur, meeting_id: str) -> None:
    cur.execute("INSERT INTO meeting_digestions (meeting_id) VALUES (%s) ON CONFLICT DO NOTHING", (meeting_id,))


def claim_transcript(identities: list[tuple[str, str]], owner: str) -> dict | None:
    return _claim(identities, owner, "d.transcript_status = 'pending' AND d.next_attempt_at <= clock_timestamp()")


def claim_digestion(identities: list[tuple[str, str]], owner: str) -> dict | None:
    return _claim(identities, owner,
                  "(d.transcript_status = 'pending' AND d.next_attempt_at <= clock_timestamp()) OR "
                  "(d.transcript_status = 'ready' AND d.memory_status = 'pending' AND d.memory_next_attempt_at <= clock_timestamp()) OR "
                  "(d.transcript_status = 'ready' AND d.memory_status = 'done' AND d.profile_status = 'pending' AND d.profile_next_attempt_at <= clock_timestamp())")


def _claim(identities: list[tuple[str, str]], owner: str, eligibility: str) -> dict | None:
    if not identities:
        return None
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 100:
        raise ValueError("Digestion claim requires a nonblank owner of at most 100 characters")
    with _cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS acquired", (_CLAIM_LOCK,))
        if not cur.fetchone()["acquired"]:
            return None
        cur.execute("SELECT 1 FROM meeting_digestions WHERE claim_until > clock_timestamp() LIMIT 1")
        if cur.fetchone():
            return None
        cur.execute(
            f"""SELECT d.meeting_id FROM meeting_digestions d
               JOIN meeting_summaries m ON m.id = d.meeting_id
               WHERE (m.provider, m.account_key) IN %s AND m.available
                 AND ({eligibility})
               ORDER BY d.created_at, d.meeting_id LIMIT 1 FOR UPDATE OF d""",
            (tuple(identities),),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            """UPDATE meeting_digestions SET claim_owner = %s,
               claim_until = clock_timestamp() + %s * interval '1 second', updated_at = clock_timestamp()
               WHERE meeting_id = %s RETURNING *""", (owner, LEASE_SECONDS, row["meeting_id"]),
        )
        return _serialize(dict(cur.fetchone()))


def _owned(cur, meeting_id: str, owner: str) -> dict:
    cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id = %s FOR UPDATE", (meeting_id,))
    row = cur.fetchone()
    cur.execute("SELECT clock_timestamp() AS now")
    now = cur.fetchone()["now"]
    if row is None or row["claim_owner"] != owner or row["claim_until"] is None or row["claim_until"] <= now:
        raise ClaimLostError("Meeting digestion claim expired or belongs to another run")
    return dict(row)


def release(meeting_id: str, owner: str) -> None:
    with _cursor() as cur:
        cur.execute(
            """UPDATE meeting_digestions SET claim_owner = NULL, claim_until = NULL,
               updated_at = clock_timestamp() WHERE meeting_id = %s AND claim_owner = %s""",
            (meeting_id, owner),
        )


def release_owner(owner: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE meeting_digestions SET claim_owner = NULL, claim_until = NULL WHERE claim_owner = %s",
            (owner,),
        )


def get_record(meeting_id: str) -> dict | None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id = %s", (meeting_id,))
        row = cur.fetchone()
        return _serialize(dict(row)) if row else None


def get_context(meeting_id: str) -> dict | None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute("SELECT * FROM meeting_summaries WHERE id = %s AND available", (meeting_id,))
        row = cur.fetchone()
        return _serialize({key: row[key] for key in _SNAPSHOT_FIELDS}) if row else None


def save_capture(meeting_id: str, owner: str, snapshot: dict, transcript: dict, *, complete: bool = False) -> None:
    if not isinstance(snapshot, dict) or not isinstance(transcript, dict):
        raise ValueError("Transcript capture requires snapshot and transcript objects")
    segments = transcript.get("segments", [])
    if not isinstance(segments, list) or len(json.dumps(transcript).encode()) > 20_000_000:
        raise ValueError("Transcript exceeds the 20000000-byte storage limit")
    if complete and not segments:
        raise ValueError("A complete transcript must contain segments")
    content_hash = hashlib.sha256(json.dumps(segments, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest() if complete else None
    with _cursor() as cur:
        _owned(cur, meeting_id, owner)
        cur.execute("SELECT provider_updated_at, revision, available FROM meeting_summaries WHERE id = %s FOR SHARE", (meeting_id,))
        meeting = cur.fetchone()
        if (not meeting or not meeting["available"] or snapshot.get("id") != meeting_id
                or meeting["revision"] != snapshot.get("revision")
                or meeting["provider_updated_at"].isoformat() != snapshot.get("provider_updated_at")):
            raise ClaimLostError("Meeting changed during transcript capture; retry after synchronization")
        cur.execute(
            """UPDATE meeting_digestions SET snapshot = %s, transcript = %s, transcript_hash = %s,
               transcript_status = %s, error_type = NULL,
               captured_at = CASE WHEN %s THEN clock_timestamp() ELSE NULL END, updated_at = clock_timestamp()
               WHERE meeting_id = %s""",
            (Json(snapshot), Json(transcript), content_hash, "ready" if complete else "pending", complete, meeting_id),
        )


def reset_capture(meeting_id: str, owner: str) -> None:
    with _cursor() as cur:
        _owned(cur, meeting_id, owner)
        cur.execute("UPDATE meeting_digestions SET transcript = '{}'::jsonb, snapshot = '{}'::jsonb, transcript_hash = NULL WHERE meeting_id = %s", (meeting_id,))


def record_failure(meeting_id: str, owner: str, error_type: str, *, status: str | None = None) -> None:
    if not error_type or not error_type.replace("_", "").isalnum() or len(error_type) > 100:
        raise ValueError("Transcript error must be a safe error category")
    if status not in {None, "unsupported", "unavailable"}:
        raise ValueError("Unknown transcript failure status")
    with _cursor() as cur:
        row = _owned(cur, meeting_id, owner)
        attempts = row["attempts"] + 1
        disposition = status or ("failed" if attempts >= 3 else "pending")
        delay = min(900, 60 * 5 ** (attempts - 1)) * random.uniform(0.8, 1.2)
        cur.execute(
            """UPDATE meeting_digestions SET transcript_status = %s, attempts = %s, error_type = %s,
               next_attempt_at = clock_timestamp() + %s * interval '1 second', updated_at = clock_timestamp()
               WHERE meeting_id = %s""", (disposition, attempts, error_type, delay, meeting_id),
        )


def get_transcript(meeting_id: str, *, limit: int = 100, offset: int = 0) -> dict | None:
    UUID(meeting_id)
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
        raise ValueError("Transcript limit must be 1-200 and offset nonnegative")
    with _cursor() as cur:
        cur.execute(
            """SELECT transcript_status, error_type, captured_at, claim_until > clock_timestamp() AS running,
               CASE WHEN transcript_status = 'ready' THEN jsonb_array_length(transcript->'segments') ELSE 0 END AS total,
               CASE WHEN transcript_status = 'ready' THEN
                 (SELECT coalesce(jsonb_agg(segment ORDER BY position), '[]'::jsonb)
                  FROM jsonb_array_elements(transcript->'segments') WITH ORDINALITY AS entries(segment, position)
                  WHERE position > %s AND position <= %s) ELSE '[]'::jsonb END AS items
               FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id = m.id
               WHERE m.id = %s AND m.available""", (offset, offset + limit, meeting_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    if row["transcript_status"] is None:
        return {"status": "not_imported", "items": [], "total": 0, "limit": limit, "offset": offset, "error_type": None, "captured_at": None}
    status = "capturing" if row["running"] and row["transcript_status"] == "pending" else row["transcript_status"]
    return _serialize({"status": status, "items": row["items"], "total": row["total"], "limit": limit, "offset": offset,
                       "error_type": row["error_type"], "captured_at": row["captured_at"]})


def delete_transcript(meeting_id: str) -> None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO meeting_digestions (meeting_id, transcript_status) VALUES (%s, 'deleted')
               ON CONFLICT (meeting_id) DO UPDATE SET transcript_status = 'deleted', transcript = '{}'::jsonb,
               snapshot = '{}'::jsonb, transcript_hash = NULL, claim_owner = NULL, claim_until = NULL,
               captured_at = NULL, error_type = NULL, updated_at = clock_timestamp()""", (meeting_id,),
        )


def retry_transcript(meeting_id: str) -> None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute(
            """UPDATE meeting_digestions SET transcript_status = 'pending', attempts = 0,
               next_attempt_at = clock_timestamp(), error_type = NULL, updated_at = clock_timestamp()
               WHERE meeting_id = %s AND transcript_status IN ('failed', 'unsupported', 'unavailable')""",
            (meeting_id,),
        )
        if cur.rowcount != 1:
            raise ValueError("Transcript capture cannot be retried in its current state")
