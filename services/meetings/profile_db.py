from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from uuid import UUID, uuid5

from psycopg2.extras import Json
from pydantic import ValidationError

from services.meetings import stage_db
from services.meetings.db import _cursor, _serialize
from services.meetings.outputs import ProfileClaim

_CLAIM_NAMESPACE = UUID("9a9b960b-0574-53ed-9f5d-9a3f67b58fd7")


class ProfileRevisionConflict(RuntimeError):
    pass


def _catalog(participants: list[dict]) -> dict[str, dict]:
    if not isinstance(participants, list) or len(participants) > 200:
        raise ValueError("Participant catalog must contain at most 200 identities")
    catalog = {}
    identities = set()
    for participant in participants:
        if not isinstance(participant, dict):
            raise ValueError("Participant must be an object")
        profile_id = str(UUID(participant["id"]))
        identity = participant.get("identity_key")
        if (profile_id in catalog or not isinstance(identity, str) or not identity.strip() or len(identity) > 1000
                or identity in identities or participant.get("identity_scope") not in {"email", "meeting"}
                or not isinstance(participant.get("display_name"), str) or not participant["display_name"].strip()
                or len(participant["display_name"]) > 1000
                or (participant.get("email") is not None and not isinstance(participant["email"], str))):
            raise ValueError("Participant identity is invalid or duplicated")
        catalog[profile_id] = {**participant, "id": profile_id}
        identities.add(identity)
    return catalog


def _visible(cur, rows: list[dict], *, include_overrides: bool = False) -> list[dict]:
    meeting_ids = {claim.get("meeting_id") for row in rows for claim in row["claims"] if claim.get("meeting_id")}
    available = set()
    if meeting_ids:
        cur.execute("SELECT id FROM meeting_summaries WHERE id IN %s AND available", (tuple(meeting_ids),))
        available = {str(row["id"]) for row in cur.fetchall()}
    result = []
    for row in rows:
        claims = []
        for claim in row["claims"]:
            if claim.get("meeting_id") in available:
                claims.append(claim)
            elif include_overrides and claim.get("status") in {"corrected", "rejected"}:
                claims.append({**claim, "evidence": [], "source_url": None, "rationale": "", "source_unavailable": True})
        result.append(_serialize({**row, "claims": claims}))
    return result


def load_profiles(participants: list[dict]) -> list[dict]:
    catalog = _catalog(participants)
    if not catalog:
        return []
    with _cursor() as cur:
        cur.execute("SELECT * FROM participant_profiles WHERE id IN %s", (tuple(catalog),))
        rows = {str(row["id"]): dict(row) for row in cur.fetchall()}
        result = []
        for profile_id, participant in catalog.items():
            existing = rows.get(profile_id)
            if existing and existing["identity_key"] != participant["identity_key"]:
                raise ProfileRevisionConflict("Participant identity changed")
            result.append(existing or {
                **{key: participant.get(key) for key in ("id", "identity_key", "display_name", "email", "identity_scope")},
                "claims": [], "revision": 0, "deleted": False, "created_at": None, "updated_at": None,
            })
        return _visible(cur, result, include_overrides=True)


def get_profile(profile_id: str) -> dict | None:
    UUID(profile_id)
    with _cursor() as cur:
        cur.execute("SELECT * FROM participant_profiles WHERE id = %s AND NOT deleted", (profile_id,))
        row = cur.fetchone()
        return _visible(cur, [dict(row)])[0] if row else None


def save_progress(meeting_id: str, owner: str, transcript_hash: str, artifact: dict) -> None:
    stage_db.save_progress("profile", meeting_id, owner, transcript_hash, artifact)


def record_failure(meeting_id: str, owner: str, error_type: str) -> None:
    stage_db.record_failure("profile", meeting_id, owner, error_type)


def reset_progress(meeting_id: str, owner: str, transcript_hash: str) -> None:
    save_progress(meeting_id, owner, transcript_hash, {})


def _validate_candidates(artifact: dict, catalog: dict[str, dict], record: dict) -> list[dict]:
    expected = artifact.get("expected_revisions")
    if not isinstance(expected, dict) or set(expected) != set(catalog) or any(type(value) is not int or value < 0 for value in expected.values()):
        raise ValueError("Profile output requires every participant revision")
    candidates = artifact.get("items")
    if not isinstance(candidates, list):
        raise ValueError("Profile output items must be an array")
    segments = {item["id"]: item["text"] for item in record["transcript"]["segments"]}
    claims = []
    for index, item in enumerate(candidates):
        try:
            item = ProfileClaim.model_validate(item).model_dump()
        except ValidationError:
            raise ValueError("Profile claim does not match the output schema") from None
        subject, target = item["subject_id"], item["target_id"]
        if subject not in catalog or (target is not None and target not in catalog):
            raise ValueError("Profile claim references an unknown participant")
        evidence = item["evidence"]
        allowed = catalog[subject].get("segment_ids", [])
        if any(entry["segment_id"] not in allowed or not entry["quote"].strip()
               or entry["quote"] not in segments.get(entry["segment_id"], "") for entry in evidence):
            raise ValueError("Profile claim requires exact evidence from its subject")
        claims.append({
            **item,
            "id": str(uuid5(_CLAIM_NAMESPACE, f"{record['meeting_id']}:{index}")),
            "meeting_id": str(record["meeting_id"]), "source_url": record["snapshot"]["source_url"],
            "transcript_hash": record["transcript_hash"],
            "target_name": catalog[target]["display_name"] if target else None,
            "status": "active", "correction": None,
        })
    return claims


def apply_profiles(meeting_id: str, owner: str, transcript_hash: str, artifact: dict, participants: list[dict]) -> list[str]:
    stage_db.validate_artifact(artifact)
    catalog = _catalog(participants)
    with _cursor() as cur:
        record = stage_db.pending(cur, meeting_id, owner, transcript_hash, "profile")
        claims = _validate_candidates(artifact, catalog, record)
        rows = {}
        if catalog:
            cur.execute("SELECT * FROM participant_profiles WHERE id IN %s ORDER BY id FOR UPDATE", (tuple(catalog),))
            rows = {str(row["id"]): dict(row) for row in cur.fetchall()}
        for profile_id in sorted(catalog):
            row = rows.get(profile_id)
            if ((row["revision"] if row else 0) != artifact["expected_revisions"][profile_id]
                    or (row and row["identity_key"] != catalog[profile_id]["identity_key"])):
                raise ProfileRevisionConflict("Participant profile changed; rebuild the profile candidate")
        for claim in claims:
            if any(rows.get(profile_id, {}).get("deleted") for profile_id in (claim["subject_id"], claim["target_id"])):
                raise ProfileRevisionConflict("A participant profile was deleted")
        applied = []
        for profile_id in sorted({claim["subject_id"] for claim in claims}):
            additions = [claim for claim in claims if claim["subject_id"] == profile_id]
            row = rows.get(profile_id)
            if row:
                stored_ids = {claim["id"] for claim in row["claims"]}
                additions = [claim for claim in additions if claim["id"] not in stored_ids]
                if additions:
                    _validate_claim_size(row["claims"] + additions)
                    cur.execute("UPDATE participant_profiles SET claims = %s, revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s",
                                (Json(row["claims"] + additions), profile_id))
            else:
                participant = catalog[profile_id]
                _validate_claim_size(additions)
                cur.execute(
                    """INSERT INTO participant_profiles (id, identity_key, display_name, email, identity_scope, claims)
                       VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id""",
                    (profile_id, participant["identity_key"], participant["display_name"], participant.get("email"), participant["identity_scope"], Json(additions)),
                )
                if not cur.fetchone():
                    raise ProfileRevisionConflict("Participant identity was created concurrently")
            applied.append(profile_id)
        completed = {**copy.deepcopy(artifact), "profile_ids": applied}
        stage_db.write_progress(cur, "profile", meeting_id, completed, complete=True)
    return applied


def _validate_claim_size(claims: list[dict]) -> None:
    if len(json.dumps(claims).encode()) > 2_000_000:
        raise ValueError("Cumulative participant profile exceeds the 2000000-byte storage limit")


def _expected_revision(value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("Expected profile revision must be a positive integer")


def _editable(cur, profile_id: str, expected_revision: int) -> dict:
    cur.execute("SELECT * FROM participant_profiles WHERE id = %s FOR UPDATE", (profile_id,))
    row = cur.fetchone()
    if row is None or row["deleted"]:
        raise ValueError("Participant profile does not exist")
    if row["revision"] != expected_revision:
        raise ProfileRevisionConflict("Participant profile changed; reload before editing")
    return dict(row)


def correct_claim(profile_id: str, claim_id: str, expected_revision: int, action: str, content: str | None, reason: str) -> dict:
    UUID(profile_id)
    UUID(claim_id)
    _expected_revision(expected_revision)
    if (action not in {"correct", "reject"} or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000
            or (action == "correct" and (not isinstance(content, str) or not content.strip() or len(content) > 2000))):
        raise ValueError("Claim correction requires a supported action, reason and corrected content")
    with _cursor() as cur:
        row = _editable(cur, profile_id, expected_revision)
        claims = copy.deepcopy(row["claims"])
        claim = next((claim for claim in claims if claim["id"] == claim_id), None)
        if claim is None:
            raise ValueError("Profile claim does not exist")
        claim["status"] = "corrected" if action == "correct" else "rejected"
        correction = {"action": action, "content": content if action == "correct" else None,
                      "reason": reason, "corrected_at": datetime.now(timezone.utc).isoformat()}
        claim.setdefault("corrections", []).append(correction)
        claim["correction"] = correction
        _validate_claim_size(claims)
        cur.execute("UPDATE participant_profiles SET claims = %s, revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s RETURNING *",
                    (Json(claims), profile_id))
        return _visible(cur, [dict(cur.fetchone())])[0]


def delete_profile(profile_id: str, expected_revision: int) -> None:
    UUID(profile_id)
    _expected_revision(expected_revision)
    with _cursor() as cur:
        _editable(cur, profile_id, expected_revision)
        cur.execute("UPDATE participant_profiles SET claims = '[]'::jsonb, deleted = true, revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s", (profile_id,))


def meeting_profiles(meeting_id: str) -> dict | None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute(
            """SELECT d.meeting_id, d.transcript_status, d.memory_status, d.profile_status, d.profile_artifact,
               d.profile_error, d.claim_until > clock_timestamp() AS running FROM meeting_summaries m
               LEFT JOIN meeting_digestions d ON d.meeting_id = m.id WHERE m.id = %s AND m.available""", (meeting_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        status, reason, items = "not_imported", None, []
        if row["meeting_id"] is not None:
            status = row["profile_status"]
            if status == "done":
                reason = row["profile_artifact"].get("reason")
                ids = row["profile_artifact"].get("profile_ids", [])
                if ids:
                    cur.execute("SELECT id, display_name, email, revision FROM participant_profiles WHERE id IN %s AND NOT deleted ORDER BY display_name, id", (tuple(ids),))
                    items = [dict(item) for item in cur.fetchall()]
            elif row["transcript_status"] != "ready":
                status, reason = "blocked", "transcript_" + row["transcript_status"]
            elif row["memory_status"] != "done":
                status, reason = "blocked", "memories_" + row["memory_status"]
            elif row["running"]:
                status = "running"
        return _serialize({"status": status, "items": items, "reason": reason, "error_type": row["profile_error"]})


def retry_profiles(meeting_id: str) -> None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute(
            """UPDATE meeting_digestions d SET profile_status = 'pending', profile_attempts = 0,
               profile_next_attempt_at = clock_timestamp(), profile_error = NULL, profile_updated_at = clock_timestamp()
               FROM meeting_summaries m WHERE d.meeting_id = m.id AND m.available AND d.meeting_id = %s
               AND d.profile_status = 'failed' AND d.transcript_status = 'ready' AND d.memory_status = 'done'""", (meeting_id,),
        )
        if cur.rowcount != 1:
            raise ValueError("Meeting profiles cannot be retried in their current state")
