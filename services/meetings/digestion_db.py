from __future__ import annotations

import hashlib
import json
import random
from uuid import UUID

from psycopg2.extras import Json

from services.meetings.db import ClaimLostError, _cursor, _serialize

LEASE_SECONDS = 600
_CLAIM_LOCK = "agent-smith:meeting-digestion"
_PROFILE_LOCK = "agent-smith:persona"
_SPEAKER_ELIGIBILITY = "d.transcript_status = 'ready' AND d.speaker_status = 'pending' AND d.speaker_next_attempt_at <= clock_timestamp()"
_MEMORY_ELIGIBILITY = f"(d.transcript_status = 'pending' AND d.next_attempt_at <= clock_timestamp()) OR ({_SPEAKER_ELIGIBILITY}) OR (d.transcript_status = 'ready' AND d.speaker_status != 'pending' AND d.memory_status = 'pending' AND d.memory_next_attempt_at <= clock_timestamp())"
_PROFILE_ELIGIBILITY = "d.transcript_status = 'ready' AND d.speaker_status != 'pending' AND d.profile_status = 'pending' AND d.profile_next_attempt_at <= clock_timestamp()"
_SNAPSHOT_FIELDS = (
    "id", "provider", "account_key", "external_id", "source_name", "project", "title",
    "summary_text", "source_url", "metadata", "provider_updated_at", "revision",
)


def enroll(cur, meeting_id: str) -> None:
    cur.execute("INSERT INTO meeting_digestions (meeting_id) VALUES (%s) ON CONFLICT DO NOTHING", (meeting_id,))


def claim_transcript(identities: list[tuple[str, str]], owner: str) -> dict | None:
    return _claim(identities, owner, "d.transcript_status = 'pending' AND d.next_attempt_at <= clock_timestamp()")


def claim_digestion(identities: list[tuple[str, str]], owner: str) -> dict | None:
    return _claim(identities, owner, _MEMORY_ELIGIBILITY)


def claim_manual_memory(identities: list[tuple[str, str]], owner: str) -> dict | None:
    eligibility = """d.transcript_status='ready' AND d.speaker_status!='pending' AND d.memory_status='pending'
        AND d.memory_next_attempt_at<=clock_timestamp() AND d.manual_analysis->'memory'->>'active'='true'"""
    return _claim(identities, owner, eligibility)


def claim_identification(source: str | None, owner: str, meeting_id: str | None = None) -> dict | None:
    if meeting_id is not None:
        meeting_id = str(UUID(meeting_id))
    eligibility = _SPEAKER_ELIGIBILITY + " AND (%s::uuid IS NULL OR d.meeting_id=%s::uuid)"
    return _claim(None, owner, eligibility, source=source, extra_params=(meeting_id, meeting_id), snapshot_participants=False)


def has_requested_identification(source: str | None = None, meeting_id: str | None = None) -> bool:
    if meeting_id is not None:
        meeting_id = str(UUID(meeting_id))
    eligibility = _SPEAKER_ELIGIBILITY + " AND (%s::uuid IS NULL OR d.meeting_id=%s::uuid)"
    return _has_requested(None, eligibility, source=source, extra_params=(meeting_id, meeting_id))


def _work_scope(identities, source):
    if identities is not None:
        return "(m.provider, m.account_key) IN %s", (tuple(identities),)
    if source is not None and (not isinstance(source, str) or not source.strip() or len(source) > 100):
        raise ValueError("Persona source must be a nonblank stored connection name of at most 100 characters")
    return "(%s IS NULL OR m.source_name = %s)", (source, source)


def claim_profile(source: str | None, owner: str) -> dict | None:
    return _claim(None, owner, _PROFILE_ELIGIBILITY, source=source, profile=True)


def has_requested_work(identities: list[tuple[str, str]], *, digest: bool = True) -> bool:
    if not identities:
        return False
    eligibility = _MEMORY_ELIGIBILITY if digest else "d.transcript_status = 'pending' AND d.next_attempt_at <= clock_timestamp()"
    return _has_requested(identities, eligibility)


def has_requested_profile_work(source: str | None = None) -> bool:
    return _has_requested(None, _PROFILE_ELIGIBILITY, source=source, profile=True)


def _has_requested(identities, eligibility, *, source=None, profile=False, extra_params=()) -> bool:
    scope, params = _work_scope(identities, source)
    lease = "profile_claim_until" if profile else "claim_until"
    with _cursor() as cur:
        cur.execute(
            f"""SELECT EXISTS (SELECT 1 FROM meeting_digestions d JOIN meeting_summaries m ON m.id = d.meeting_id
                WHERE m.available AND d.requested_at IS NOT NULL AND ({scope}) AND ({eligibility}))
                AND NOT EXISTS (SELECT 1 FROM meeting_digestions WHERE {lease} > clock_timestamp()) AS due""", (*params, *extra_params),
        )
        return cur.fetchone()["due"]


def _claim(identities, owner: str, eligibility: str, *, source=None, profile=False, extra_params=(), snapshot_participants=True) -> dict | None:
    if identities is not None and not identities:
        return None
    if not isinstance(owner, str) or not owner.strip() or len(owner) > 100:
        raise ValueError("Digestion claim requires a nonblank owner of at most 100 characters")
    scope, params = _work_scope(identities, source)
    prefix = "profile_" if profile else ""
    with _cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0)) AS acquired", (_PROFILE_LOCK if profile else _CLAIM_LOCK,))
        if not cur.fetchone()["acquired"]:
            return None
        cur.execute(f"SELECT 1 FROM meeting_digestions WHERE {prefix}claim_until > clock_timestamp() LIMIT 1")
        if cur.fetchone():
            return None
        cur.execute(
            f"""SELECT d.meeting_id, m.manual_participants, m.participants_revision FROM meeting_digestions d
               JOIN meeting_summaries m ON m.id = d.meeting_id
               WHERE ({scope}) AND m.available
                 AND ({eligibility})
               ORDER BY (d.requested_at IS NULL), d.requested_at, d.created_at, d.meeting_id
               LIMIT 1 FOR UPDATE OF d FOR SHARE OF m""",
            (*params, *extra_params),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            f"""UPDATE meeting_digestions SET {prefix}claim_owner = %s,
               {prefix}claim_until = clock_timestamp() + %s * interval '1 second', updated_at = clock_timestamp(),
               participant_snapshot = CASE WHEN %s THEN %s ELSE participant_snapshot END,
               participants_revision = CASE WHEN %s THEN %s ELSE participants_revision END
               WHERE meeting_id = %s RETURNING *""",
            (owner, LEASE_SECONDS, snapshot_participants, Json(row["manual_participants"]), snapshot_participants, row["participants_revision"], row["meeting_id"]),
        )
        return _serialize(dict(cur.fetchone()))


def _owned(cur, meeting_id: str, owner: str, *, profile: bool = False) -> dict:
    cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id = %s FOR UPDATE", (meeting_id,))
    row = cur.fetchone()
    cur.execute("SELECT clock_timestamp() AS now")
    now = cur.fetchone()["now"]
    prefix = "profile_" if profile else ""
    if row is None or row[prefix + "claim_owner"] != owner or row[prefix + "claim_until"] is None or row[prefix + "claim_until"] <= now:
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
    _release_owner(owner, profile=False)


def release_profile_owner(owner: str) -> None:
    _release_owner(owner, profile=True)


def _release_owner(owner: str, *, profile: bool) -> None:
    prefix = "profile_" if profile else ""
    with _cursor() as cur:
        cur.execute(
            f"UPDATE meeting_digestions SET {prefix}claim_owner = NULL, {prefix}claim_until = NULL WHERE {prefix}claim_owner = %s",
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
            """SELECT m.id, m.manual_participants, m.metadata, transcript_status, error_type, captured_at, transcript_hash,speaker_artifact,claim_until > clock_timestamp() AS running,
               CASE WHEN transcript_status = 'ready' THEN jsonb_array_length(transcript->'segments') ELSE 0 END AS total,
               CASE WHEN transcript_status = 'ready' THEN
                 (SELECT coalesce(jsonb_agg(segment ORDER BY position), '[]'::jsonb)
                  FROM jsonb_array_elements(transcript->'segments') WITH ORDINALITY AS entries(segment, position)
                  WHERE position > %s AND position <= %s) ELSE '[]'::jsonb END AS items
               FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id = m.id
               WHERE m.id = %s AND m.available""", (offset, offset + limit, meeting_id),
        )
        row = cur.fetchone()
        if row and row["transcript_status"] == "ready":
            from services.meetings.participants_db import effective_speakers
            from services.meetings.speaker_db import committed

            speakers = effective_speakers(cur, {**dict(row), "statement_attributions": committed(dict(row))}, row["items"])
            manual = {person["segment_id"]: person for person in row["manual_participants"] if person.get("segment_id")}
            row["items"] = [{**segment, "effective_speaker": speakers.get(segment["id"]), "speaker_assignment": manual.get(segment["id"])} for segment in row["items"]]
    if row is None:
        return None
    from services.meetings import stage_state

    return _serialize({**stage_state.transcript(dict(row)), "transcript_hash": row["transcript_hash"],
                       "items": row["items"], "limit": limit, "offset": offset})


def delete_transcript(meeting_id: str) -> None:
    UUID(meeting_id)
    with _cursor() as cur:
        from services.meetings import manual_stage

        manual_stage.invalidate_source(cur, meeting_id)
        cur.execute(
            """INSERT INTO meeting_digestions (meeting_id, transcript_status) VALUES (%s, 'deleted')
               ON CONFLICT (meeting_id) DO UPDATE SET transcript_status = 'deleted', transcript = '{}'::jsonb,
               snapshot = '{}'::jsonb, transcript_hash = NULL, claim_owner = NULL, claim_until = NULL,
               profile_claim_owner = NULL, profile_claim_until = NULL,
               captured_at = NULL, error_type = NULL, updated_at = clock_timestamp()""", (meeting_id,),
        )


def retry_transcript(meeting_id: str) -> None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute(
            """UPDATE meeting_digestions SET transcript_status = 'pending', attempts = 0,
               next_attempt_at = clock_timestamp(), error_type = NULL, updated_at = clock_timestamp(),
               requested_at = coalesce(requested_at, clock_timestamp())
               WHERE meeting_id = %s AND transcript_status IN ('failed', 'unsupported', 'unavailable')""",
            (meeting_id,),
        )
        if cur.rowcount != 1:
            raise ValueError("Transcript capture cannot be retried in its current state")
