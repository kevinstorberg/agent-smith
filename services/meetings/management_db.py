from __future__ import annotations

import copy
import re
from contextlib import contextmanager
from uuid import UUID

from psycopg2.extras import Json

from services.meetings import digestion_db, profile_db
from services.meetings.db import _cursor, _serialize
from services.meetings.participants import current_manual, email_participant, meeting_participants, speaker_key


class MeetingManagementConflict(RuntimeError):
    pass


class MeetingNotFoundError(LookupError):
    pass


@contextmanager
def _editable(meeting_id: str, *, allow_running: bool = False):
    UUID(meeting_id)
    with profile_db.profile_write_cursor() as cur:
        cur.execute("SELECT *, coalesce(claim_until > clock_timestamp(),false) AS memory_running, coalesce(profile_claim_until > clock_timestamp(),false) AS persona_running FROM meeting_digestions WHERE meeting_id = %s FOR UPDATE", (meeting_id,))
        digestion = cur.fetchone()
        cur.execute("SELECT * FROM meeting_summaries WHERE id = %s AND available FOR UPDATE", (meeting_id,))
        meeting = cur.fetchone()
        if meeting is None:
            raise MeetingNotFoundError("Meeting not found")
        if digestion:
            digestion = dict(digestion)
            digestion["running"] = digestion["memory_running"] or digestion["persona_running"]
            reason = _edit_lock(digestion)
            if reason and not allow_running:
                raise MeetingManagementConflict(_LOCK_MESSAGES[reason])
        yield cur, dict(meeting), dict(digestion) if digestion else None


_LOCK_MESSAGES = {
    "capturing_transcript": "Participant changes are available after transcript capture finishes.",
    "identifying_participants": "Participant changes are available after speaker identification finishes.",
    "analyzing_personas": "Participant changes are available after the current persona review finishes.",
}


def _edit_lock(row: dict) -> str | None:
    if row.get("persona_running"):
        return "analyzing_personas"
    if row.get("memory_running"):
        if row.get("transcript_status") == "pending":
            return "capturing_transcript"
        if row.get("speaker_status") == "pending":
            return "identifying_participants"
    return None


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
        """SELECT m.manual_participants, m.participants_revision, m.metadata,d.transcript_hash,d.transcript_status,
           d.speaker_status,d.speaker_artifact,d.speaker_attempts,d.speaker_error,d.speaker_next_attempt_at,
           d.meeting_id IS NOT NULL AS enrolled,
           coalesce(d.claim_until > clock_timestamp(), false) AS memory_running,
           coalesce(d.profile_claim_until > clock_timestamp(), false) AS persona_running
           FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id = m.id
           WHERE m.id = %s AND m.available""", (meeting_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    speakers = _speaker_groups(cur, meeting_id)
    from services.meetings.participants_db import effective_speakers

    from services.meetings import stage_db

    snapshot = {"id": meeting_id, "manual_participants": [person for person in row["manual_participants"] if not person.get("segment_id")],
                "metadata": row["metadata"]}
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
        "running": row["memory_running"] or row["persona_running"], "enrolled": row["enrolled"],
        "transcript_hash": row["transcript_hash"], "edit_lock_reason": _edit_lock(dict(row)),
        "attribution": {"status": "running" if row["speaker_status"] == "pending" and row["memory_running"] else row["speaker_status"] or "not_imported",
                        "error_type": row["speaker_error"], "progress": stage_db.progress(dict(row), "speaker")},
        "stale_segment_ids": _stale_segments(cur, meeting_id, row["manual_participants"]),
        "stale_speaker_keys": sorted({item["speaker_key"] for item in row["manual_participants"] if item.get("speaker_key") and item["speaker_key"] not in keys}),
    })


def _stale_segments(cur, meeting_id: str, participants: list[dict]) -> list[str]:
    ids = {person["segment_id"] for person in participants if person.get("segment_id")}
    if not ids:
        return []
    cur.execute("SELECT entry->>'id' AS id FROM meeting_digestions d,jsonb_array_elements(d.transcript->'segments') entry WHERE d.meeting_id=%s", (meeting_id,))
    return sorted(ids - {row["id"] for row in cur.fetchall()})


def get_participants(meeting_id: str) -> dict | None:
    UUID(meeting_id)
    with _cursor() as cur:
        return _participants(cur, meeting_id)


def _normalize_participants(cur, participants: list[dict], speakers: set[str], segment_ids: set[str] | None = None) -> list[dict]:
    if not isinstance(participants, list) or len(participants) > 200:
        raise ValueError("Participants must be an array of at most 200 people")
    normalized, assigned = [], set()
    for item in participants:
        if not isinstance(item, dict) or set(item) - {"name", "email", "profile_id", "speaker_key", "segment_id"}:
            raise ValueError("Participant fields must be name, email, profile_id, speaker_key and segment_id")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise ValueError("Participant name must be nonblank and at most 200 characters")
        person = {"name": name.strip()}
        if item.get("speaker_key") is not None and item.get("segment_id") is not None:
            raise ValueError("Choose a statement or transcript speaker, not both")
        if item.get("segment_id") is not None:
            segment_id = item["segment_id"]
            if not isinstance(segment_id, str) or segment_id not in (segment_ids or set()):
                raise ValueError("Select a statement from the saved transcript")
            if segment_id in assigned:
                raise ValueError("A transcript statement can only be assigned to one participant")
            assigned.add(segment_id)
            person["segment_id"] = segment_id
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


def _retire_changed_attribution(cur, meeting: dict, digestion: dict, participants: list[dict], *, old_attributions=None, new_attributions=None) -> tuple[list[str], bool]:
    from services.meetings import profile_metadata
    from services.personas import revisions, sections

    segments = digestion["transcript"].get("segments", [])
    if not segments:
        return [], False
    old = current_manual(meeting["manual_participants"], segments)
    from services.meetings.speaker_db import committed

    base = digestion["snapshot"]
    attributions = [committed(digestion) if value is None else value for value in (old_attributions, new_attributions)]
    catalogs = [profile_db.resolve_participants(meeting_participants({**base, "manual_participants": entries, "statement_attributions": generated}, segments), cursor=cur)
                for entries, generated in zip((old, participants), attributions)]
    mappings = [{segment_id: person["id"] for person in catalog for segment_id in person["segment_ids"]} for catalog in catalogs]
    changed = {key for key in mappings[0] | mappings[1] if mappings[0].get(key) != mappings[1].get(key)}
    changed_people = {mappings[0][key] for key in changed if key in mappings[0]}
    cur.execute(
        """SELECT * FROM participant_profiles p WHERE NOT p.deleted AND p.merged_into IS NULL AND EXISTS
           (SELECT 1 FROM jsonb_array_elements(p.claims) claim WHERE claim->>'meeting_id' = %s
            UNION ALL SELECT 1 FROM jsonb_each(p.metadata_provenance) field WHERE field.value->>'meeting_id' = %s)
           ORDER BY id FOR UPDATE""", (str(meeting["id"]), str(meeting["id"])),
    )
    rows = [dict(row) for row in cur.fetchall()]
    target_ids = {claim.get("target_id") for row in rows for claim in row["claims"] if claim.get("target_id")}
    targets = profile_db.canonical_rows(cur, target_ids, metadata_only=True) if target_ids else {}
    contexts = profile_db._source_contexts(cur, rows,
        {claim["meeting_id"] for row in rows for claim in row["claims"] if claim.get("meeting_id")})
    future = copy.deepcopy(contexts)
    meeting_id, revision = str(meeting["id"]), meeting["participants_revision"] + 1
    if meeting_id in future:
        future[meeting_id]["participants_revision"] = revision
    clean_rebased = []
    for row in rows:
        claims = copy.deepcopy(row["claims"])
        retired = False
        for claim in claims:
            target = targets.get(claim.get("target_id")) or {}
            if claim.get("meeting_id") == meeting_id and not claim.get("superseded"):
                if (any(evidence["segment_id"] in changed for evidence in claim["evidence"])
                        or str(target.get("id", claim.get("target_id"))) in changed_people):
                    claim["superseded"] = True
                    retired = True
                elif profile_metadata.claim_source_valid(claim, contexts):
                    claim["participants_revision"] = revision
        provenance = profile_metadata.rebase_attribution(row, meeting_id, revision, contexts, mappings)
        evidence = sections.rebase_attribution(row, claims, contexts, future, meeting_id, revision)
        new = {**row, "claims": claims, "metadata_provenance": provenance, "section_evidence": evidence}
        valid = sections.effective_claims(new, future)
        invalidated = (retired or any(source.get("meeting_id") == meeting_id and not profile_metadata.source_valid(source, future)
                                    for source in provenance.values())
                       or any(proof.get("status") == "supported" and not proof.get("human")
                              and not sections.proof_valid(proof, valid, future) for proof in evidence.values()))
        if any(new[key] != row[key] for key in ("claims", "metadata_provenance", "section_evidence")) or invalidated:
            profile_db._validate_claim_size(claims)
            dirty = row["assessment_dirty"] or invalidated
            cur.execute("""UPDATE participant_profiles SET claims = %s, metadata_provenance = %s, section_evidence = %s,
                assessment_dirty = %s, assessment_attempts = CASE WHEN %s THEN 0 ELSE assessment_attempts END,
                assessment_error = CASE WHEN %s THEN NULL ELSE assessment_error END,
                assessment_next_attempt_at = CASE WHEN %s THEN now() ELSE assessment_next_attempt_at END,
                revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s RETURNING *""",
                        (Json(claims), Json(provenance), Json(evidence), dirty, dirty, dirty, dirty, row["id"]))
            updated = dict(cur.fetchone())
            revisions.record(cur, row, updated, actor="system", source="meeting", source_id=meeting_id)
            if not dirty and row["assessment_input_hash"]:
                clean_rebased.append(str(row["id"]))
    return clean_rebased, bool(changed)


def _refresh_rebased(cur, rebased: list[str]) -> None:
    from services.personas import assessment_db, sections

    for profile_id in rebased:
        row = profile_db._canonical(cur, profile_id)
        visible, claims = assessment_db._snapshot(cur, row)
        cur.execute("UPDATE participant_profiles SET assessment_input_hash=%s WHERE id=%s",
                    (sections.input_hash(visible, claims), profile_id))


def update_participants(meeting_id: str, expected_revision: int, participants: list[dict], expected_transcript_hash: str | None = None) -> dict:
    if type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("Expected participant revision must be a nonnegative integer")
    with _editable(meeting_id) as (cur, meeting, digestion):
        if meeting["participants_revision"] != expected_revision:
            raise MeetingManagementConflict("Participants changed. Review the latest version before saving again.")
        if expected_transcript_hash is not None and (not digestion or digestion["transcript_hash"] != expected_transcript_hash):
            raise MeetingManagementConflict("The transcript changed. Reload its statements before saving again.")
        if any(item.get("segment_id") for item in participants if isinstance(item, dict)) and expected_transcript_hash is None:
            raise ValueError("Statement assignments require the captured transcript hash")
        segments = digestion["transcript"].get("segments", []) if digestion else []
        entries = _normalize_participants(cur, participants, {group["key"] for group in _speaker_groups(cur, meeting_id)}, {segment["id"] for segment in segments})
        if entries == meeting["manual_participants"]:
            return _participants(cur, meeting_id)
        rebased, mapping_changed = _retire_changed_attribution(cur, meeting, digestion, entries) if digestion and digestion["transcript_status"] == "ready" else ([], False)
        cur.execute("UPDATE meeting_summaries SET manual_participants = %s, participants_revision = participants_revision + 1 WHERE id = %s", (Json(entries), meeting_id))
        _refresh_rebased(cur, rebased)
        if digestion:
            artifact = copy.deepcopy(digestion["speaker_artifact"])
            if mapping_changed and digestion["profile_status"] == "done":
                artifact["profile_repair_required"] = True
            if digestion["speaker_status"] == "pending":
                artifact = {key: artifact[key] for key in ("assignments", "committed_transcript_hash", "repair", "profile_repair_required") if key in artifact}
                cur.execute("UPDATE meeting_digestions SET speaker_artifact=%s,speaker_attempts=0,speaker_error=NULL,speaker_next_attempt_at=clock_timestamp() WHERE meeting_id=%s", (Json(artifact), meeting_id))
            elif artifact != digestion["speaker_artifact"]:
                cur.execute("UPDATE meeting_digestions SET speaker_artifact=%s WHERE meeting_id=%s", (Json(artifact), meeting_id))
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
