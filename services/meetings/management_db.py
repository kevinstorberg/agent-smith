from __future__ import annotations

import copy
import re
from contextlib import contextmanager
from uuid import UUID

from psycopg2.extras import Json

from services.meetings import digestion_db, profile_db
from services.meetings.db import _cursor, _serialize
from services.meetings.participants import email_participant, meeting_participants, speaker_key


class MeetingManagementConflict(RuntimeError):
    pass


class MeetingNotFoundError(LookupError):
    pass


@contextmanager
def _editable(meeting_id: str, *, allow_running: bool = False):
    UUID(meeting_id)
    with profile_db.profile_write_cursor() as cur:
        cur.execute("SELECT *, (claim_until > clock_timestamp() OR profile_claim_until > clock_timestamp()) AS running FROM meeting_digestions WHERE meeting_id = %s FOR UPDATE", (meeting_id,))
        digestion = cur.fetchone()
        cur.execute("SELECT * FROM meeting_summaries WHERE id = %s AND available FOR UPDATE", (meeting_id,))
        meeting = cur.fetchone()
        if meeting is None:
            raise MeetingNotFoundError("Meeting not found")
        if digestion and digestion["running"] and not allow_running:
            raise MeetingManagementConflict("This meeting is processing. Wait for it to finish before changing participants.")
        yield cur, dict(meeting), dict(digestion) if digestion else None


def _speaker_groups(cur, meeting_id: str) -> list[dict]:
    cur.execute(
        """SELECT entry->'speaker' AS speaker, count(*) AS segment_count, left(min(entry->>'text'), 160) AS sample
           FROM meeting_digestions d, jsonb_array_elements(d.transcript->'segments') entry
           WHERE d.meeting_id = %s AND d.transcript_status = 'ready'
           GROUP BY entry->'speaker'""", (meeting_id,),
    )
    groups = {}
    for row in cur.fetchall():
        speaker = row["speaker"] or {}
        key = speaker_key(speaker)
        label = speaker.get("name") or speaker.get("diarization_label") or speaker.get("email") or "Unidentified speaker"
        group = groups.setdefault(key, {"key": key, "label": label, "segment_count": 0,
                                      "source": speaker.get("source"), "attribution": speaker.get("attribution"),
                                      "sample": row["sample"] or "", "speaker": speaker})
        group["segment_count"] += row["segment_count"]
    return sorted(groups.values(), key=lambda group: (group["label"].casefold(), group["key"]))


def _participants(cur, meeting_id: str) -> dict | None:
    cur.execute(
        """SELECT m.manual_participants, m.participants_revision, m.metadata,
           d.meeting_id IS NOT NULL AS enrolled,
           coalesce(d.claim_until > clock_timestamp(), false) OR coalesce(d.profile_claim_until > clock_timestamp(), false) AS running
           FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id = m.id
           WHERE m.id = %s AND m.available""", (meeting_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    speakers = _speaker_groups(cur, meeting_id)
    from services.meetings.participants_db import effective_speakers

    snapshot = {"id": meeting_id, "manual_participants": row["manual_participants"], "metadata": row["metadata"]}
    effective = effective_speakers(cur, snapshot, [{"id": group["key"], "speaker": group["speaker"], "text": group["sample"]} for group in speakers])
    assignments = {entry["speaker_key"]: entry for entry in row["manual_participants"] if entry.get("speaker_key")}
    for group in speakers:
        group.pop("speaker")
        group["assignment"] = assignments.get(group["key"])
        group["effective_speaker"] = effective.get(group["key"])
    keys = {group["key"] for group in speakers}
    return _serialize({
        "revision": row["participants_revision"], "items": row["manual_participants"],
        "provider_participants": row["metadata"].get("attendees", []), "speakers": speakers,
        "running": row["running"], "enrolled": row["enrolled"],
        "stale_speaker_keys": sorted({item["speaker_key"] for item in row["manual_participants"] if item.get("speaker_key") and item["speaker_key"] not in keys}),
    })


def get_participants(meeting_id: str) -> dict | None:
    UUID(meeting_id)
    with _cursor() as cur:
        return _participants(cur, meeting_id)


def _normalize_participants(cur, participants: list[dict], speakers: set[str]) -> list[dict]:
    if not isinstance(participants, list) or len(participants) > 200:
        raise ValueError("Participants must be an array of at most 200 people")
    normalized, assigned = [], set()
    for item in participants:
        if not isinstance(item, dict) or set(item) - {"name", "email", "profile_id", "speaker_key"}:
            raise ValueError("Participant fields must be name, email, profile_id and speaker_key")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError("Participant name must be nonblank and at most 200 characters")
        person = {"name": name.strip()}
        if item.get("email") is not None:
            person["email"] = email_participant(item["email"])["email"]
        if item.get("profile_id") is not None:
            person["profile_id"] = str(UUID(item["profile_id"]))
        if item.get("speaker_key") is not None:
            key = item["speaker_key"]
            if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key) or key not in speakers:
                raise ValueError("Select a speaker from the saved transcript, or leave the speaker unassigned")
            if key in assigned:
                raise ValueError("A transcript speaker can only be assigned to one participant")
            assigned.add(key)
            person["speaker_key"] = key
        if person in normalized:
            raise ValueError("A participant cannot be listed twice with the same assignment")
        normalized.append(person)
    ids = {person["profile_id"] for person in normalized if person.get("profile_id")}
    if ids:
        rows = profile_db.canonical_rows(cur, ids, metadata_only=True)
        if any(not rows.get(profile_id) or rows[profile_id]["deleted"] for profile_id in ids):
            raise ValueError("Select an existing profile that has not been deleted")
    return normalized


def _retire_changed_attribution(cur, meeting: dict, digestion: dict, participants: list[dict]) -> None:
    segments = digestion["transcript"].get("segments", [])
    if not segments:
        return
    available_keys = {speaker_key(segment.get("speaker") or {}) for segment in segments}
    old = [item for item in meeting["manual_participants"] if not item.get("speaker_key") or item["speaker_key"] in available_keys]
    base = digestion["snapshot"]
    catalogs = [profile_db.resolve_participants(meeting_participants({**base, "manual_participants": entries}, segments), cursor=cur) for entries in (old, participants)]
    mappings = [{segment_id: person["id"] for person in catalog for segment_id in person["segment_ids"]} for catalog in catalogs]
    changed = {key for key in mappings[0] | mappings[1] if mappings[0].get(key) != mappings[1].get(key)}
    changed_people = {mappings[0][key] for key in changed if key in mappings[0]}
    if not changed:
        return
    cur.execute(
        """SELECT * FROM participant_profiles p WHERE p.merged_into IS NULL AND EXISTS
           (SELECT 1 FROM jsonb_array_elements(p.claims) claim WHERE claim->>'meeting_id' = %s)
           ORDER BY id FOR UPDATE""", (str(meeting["id"]),),
    )
    rows = [dict(row) for row in cur.fetchall()]
    target_ids = {claim.get("target_id") for row in rows for claim in row["claims"] if claim.get("target_id")}
    targets = profile_db.canonical_rows(cur, target_ids, metadata_only=True) if target_ids else {}
    for row in rows:
        claims = copy.deepcopy(row["claims"])
        altered = False
        for claim in claims:
            target = targets.get(claim.get("target_id")) or {}
            if claim.get("meeting_id") == str(meeting["id"]) and not claim.get("superseded") and (
                any(evidence["segment_id"] in changed for evidence in claim["evidence"])
                or str(target.get("id", claim.get("target_id"))) in changed_people
            ):
                claim["superseded"] = True
                altered = True
        if altered:
            profile_db._validate_claim_size(claims)
            cur.execute("UPDATE participant_profiles SET claims = %s, revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s", (Json(claims), row["id"]))


def update_participants(meeting_id: str, expected_revision: int, participants: list[dict]) -> dict:
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("Expected participant revision must be a nonnegative integer")
    with _editable(meeting_id) as (cur, meeting, digestion):
        if meeting["participants_revision"] != expected_revision:
            raise MeetingManagementConflict("Participants changed. Review the latest version before saving again.")
        entries = _normalize_participants(cur, participants, {group["key"] for group in _speaker_groups(cur, meeting_id)})
        if entries == meeting["manual_participants"]:
            return _participants(cur, meeting_id)
        if digestion and digestion["transcript_status"] == "ready":
            _retire_changed_attribution(cur, meeting, digestion, entries)
        cur.execute("UPDATE meeting_summaries SET manual_participants = %s, participants_revision = participants_revision + 1 WHERE id = %s", (Json(entries), meeting_id))
        if digestion:
            cur.execute(
                """UPDATE meeting_digestions SET profile_status = 'pending', profile_artifact = '{}'::jsonb,
                   profile_attempts = 0, profile_error = NULL, profile_next_attempt_at = clock_timestamp(),
                   profile_updated_at = clock_timestamp(), updated_at = clock_timestamp(),
                   requested_at = coalesce(requested_at, clock_timestamp()) WHERE meeting_id = %s AND profile_status != 'done'""", (meeting_id,),
            )
        return _participants(cur, meeting_id)


def request_processing(meeting_id: str) -> dict:
    with _editable(meeting_id, allow_running=True) as (cur, _, digestion):
        if digestion and digestion["running"]:
            return {"status": "running"}
        if digestion and digestion["transcript_status"] == "deleted":
            raise ValueError("This transcript was explicitly deleted and will not be restored by processing")
        if digestion and digestion["profile_status"] == "done" and digestion["memory_status"] == "done":
            return {"status": "done"}
        digestion_db.enroll(cur, meeting_id)
        cur.execute(
            """UPDATE meeting_digestions SET requested_at = coalesce(requested_at, clock_timestamp()),
               transcript_status = CASE WHEN transcript_status IN ('failed', 'unsupported', 'unavailable') THEN 'pending' ELSE transcript_status END,
               attempts = 0, error_type = NULL, next_attempt_at = clock_timestamp(),
               memory_status = CASE WHEN memory_status = 'failed' THEN 'pending' ELSE memory_status END,
               memory_attempts = 0, memory_error = NULL, memory_next_attempt_at = clock_timestamp(),
               profile_status = CASE WHEN profile_status = 'failed' THEN 'pending' ELSE profile_status END,
               profile_attempts = 0, profile_error = NULL, profile_next_attempt_at = clock_timestamp(),
               updated_at = clock_timestamp() WHERE meeting_id = %s""", (meeting_id,),
        )
        return {"status": "queued"}
