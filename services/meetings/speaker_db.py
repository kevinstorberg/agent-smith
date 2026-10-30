from __future__ import annotations

import copy

from psycopg2.extras import Json

from services.meetings import profile_db, stage_db
from services.meetings.db import _cursor


class AttributionInputChanged(RuntimeError):
    pass


class PersonaAttributionBusy(RuntimeError):
    pass


def committed(record: dict) -> list[dict]:
    artifact = record.get("speaker_artifact") or {}
    return artifact.get("assignments", []) if artifact.get("committed_transcript_hash") == record.get("transcript_hash") else []


def context_snapshot(record: dict, *, manual: list[dict] | None = None) -> dict:
    from services.meetings.participants import current_manual

    entries = record.get("participant_snapshot", []) if manual is None else manual
    return {**record["snapshot"], "manual_participants": current_manual(entries, record["transcript"].get("segments", [])),
            "participants_revision": record.get("participants_revision", 0), "statement_attributions": committed(record)}


def prepare(meeting_id: str, owner: str, transcript_hash: str) -> tuple[dict, dict]:
    with _cursor() as cur:
        record = stage_db.pending(cur, meeting_id, owner, transcript_hash, "speaker")
        cur.execute("SELECT *, clock_timestamp() AS checked_at FROM meeting_summaries WHERE id=%s FOR SHARE", (meeting_id,))
        meeting = dict(cur.fetchone())
        if record.get("profile_claim_until") and record["profile_claim_until"] > meeting["checked_at"]:
            raise PersonaAttributionBusy("An active persona review is finishing its participant snapshot")
        artifact = copy.deepcopy(record["speaker_artifact"])
        if (artifact.get("input_transcript_hash") != transcript_hash
                or artifact.get("input_participants_revision") != meeting["participants_revision"]):
            artifact = {key: artifact[key] for key in ("assignments", "committed_transcript_hash", "repair", "profile_repair_required") if key in artifact}
            artifact.update(version=1, offset=0, draft_assignments=[], input_transcript_hash=transcript_hash,
                            input_participants_revision=meeting["participants_revision"], manual_snapshot=meeting["manual_participants"])
        return record, artifact


def _current(cur, meeting_id: str, owner: str, transcript_hash: str, artifact: dict) -> tuple[dict, dict]:
    record = stage_db.pending(cur, meeting_id, owner, transcript_hash, "speaker")
    cur.execute("SELECT *,clock_timestamp() AS checked_at FROM meeting_summaries WHERE id=%s FOR UPDATE", (meeting_id,))
    meeting = dict(cur.fetchone())
    if meeting["participants_revision"] != artifact.get("input_participants_revision"):
        raise AttributionInputChanged("Participant assignments changed; restart only the unfinished identification draft")
    if record.get("profile_claim_until") and record["profile_claim_until"] > meeting["checked_at"]:
        raise PersonaAttributionBusy("An active persona review is finishing its participant snapshot")
    return record, meeting


def save_progress(meeting_id: str, owner: str, transcript_hash: str, artifact: dict) -> None:
    stage_db.validate_artifact(artifact)
    with _cursor() as cur:
        _current(cur, meeting_id, owner, transcript_hash, artifact)
        stage_db.write_progress(cur, "speaker", meeting_id, artifact)


def _mapping(cur, snapshot: dict, segments: list[dict]) -> dict:
    from services.meetings.participants import current_manual, meeting_participants

    snapshot = {**snapshot, "manual_participants": current_manual(snapshot.get("manual_participants", []), segments)}
    return {segment_id: person["id"] for person in profile_db.resolve_participants(meeting_participants(snapshot, segments), cursor=cur)
            for segment_id in person["segment_ids"]}


def apply(meeting_id: str, owner: str, transcript_hash: str, artifact: dict) -> bool:
    from services.meetings import management_db, manual_stage

    stage_db.validate_artifact(artifact)
    with profile_db.profile_write_cursor() as cur:
        record, meeting = _current(cur, meeting_id, owner, transcript_hash, artifact)
        assignments = artifact.get("draft_assignments", [])
        ids = {entry["profile_id"] for entry in assignments if entry.get("profile_id")}
        if ids:
            profiles = profile_db.canonical_rows(cur, ids, metadata_only=True)
            if any(not profiles.get(profile_id) or profiles[profile_id]["deleted"] for profile_id in ids):
                raise ValueError("An identified profile was deleted; retry participant identification")
        segments = record["transcript"]["segments"]
        base = context_snapshot(record, manual=meeting["manual_participants"])
        before, after = committed(record), assignments
        changed = _mapping(cur, {**base, "statement_attributions": before}, segments) != _mapping(cur, {**base, "statement_attributions": after}, segments)
        if changed:
            rebased, _ = management_db._retire_changed_attribution(cur, meeting, record, meeting["manual_participants"],
                                                               old_attributions=before, new_attributions=after)
            cur.execute("UPDATE meeting_summaries SET participants_revision=participants_revision+1 WHERE id=%s", (meeting_id,))
            management_db._refresh_rebased(cur, rebased)
            reopen = bool(artifact.get("repair"))
            if not manual_stage.protected_profile(record):
                cur.execute("""UPDATE meeting_digestions SET participants_revision=%s,participant_snapshot=%s,
                    profile_status=CASE WHEN profile_status!='done' OR %s THEN 'pending' ELSE profile_status END,
                    profile_artifact=CASE WHEN profile_status!='done' OR %s THEN '{}'::jsonb ELSE profile_artifact END,
                    profile_attempts=0,profile_error=NULL,profile_next_attempt_at=clock_timestamp() WHERE meeting_id=%s""",
                        (meeting["participants_revision"] + 1, Json(meeting["manual_participants"]), reopen, reopen, meeting_id))
        if artifact.get("repair") and artifact.get("profile_repair_required") and not manual_stage.protected_profile(record):
            cur.execute("""UPDATE meeting_digestions SET profile_status='pending',profile_artifact='{}'::jsonb,
                profile_attempts=0,profile_error=NULL,profile_next_attempt_at=clock_timestamp() WHERE meeting_id=%s""", (meeting_id,))
        cur.execute("UPDATE meeting_digestions SET participant_snapshot=%s,participants_revision=%s WHERE meeting_id=%s",
                    (Json(meeting["manual_participants"]), meeting["participants_revision"] + int(changed), meeting_id))
        complete = {**artifact, "assignments": assignments, "draft_assignments": [], "committed_transcript_hash": transcript_hash,
                    "changed": changed, "repair": False,
                    "profile_repair_required": bool(artifact.get("profile_repair_required")) and not artifact.get("repair", False)}
        stage_db.write_progress(cur, "speaker", meeting_id, complete, complete=True)
        manual_stage.invalidate_source(cur, meeting_id)
        return changed


def record_failure(meeting_id: str, owner: str, error_type: str) -> None:
    stage_db.record_failure("speaker", meeting_id, owner, error_type)


def request_identification(meeting_id: str) -> dict:
    from services.meetings import management_db

    with management_db._editable(meeting_id, allow_running=True) as (cur, _, record):
        if not record or record["transcript_status"] != "ready":
            raise ValueError("Capture a transcript before identifying its participants")
        if record["running"]:
            raise management_db.MeetingManagementConflict("This meeting is processing. Retry identification after its current stage finishes.")
        artifact = {key: record["speaker_artifact"][key] for key in ("assignments", "committed_transcript_hash", "profile_repair_required") if key in record["speaker_artifact"]}
        artifact["repair"] = True
        cur.execute("""UPDATE meeting_digestions SET speaker_status='pending',speaker_artifact=%s,speaker_attempts=0,
            speaker_error=NULL,speaker_next_attempt_at=clock_timestamp(),speaker_updated_at=clock_timestamp(),
            requested_at=clock_timestamp() WHERE meeting_id=%s""", (Json(artifact), meeting_id))
        return {"status": "queued"}
