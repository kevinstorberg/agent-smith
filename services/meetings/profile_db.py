from __future__ import annotations

import copy
import json
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from typing import get_args
from uuid import UUID, uuid4, uuid5

from psycopg2.extras import Json
from psycopg2.errors import LockNotAvailable
from pydantic import ValidationError

from services.meetings import stage_db
from services.meetings.db import _cursor, _serialize
from services.meetings.outputs import (ProfileClaim, ProfileMetadataPatch, ProfileCategory, ProfileEpistemic,
                                      ProfileConfidence, ProfileReviewStatus, ProfileClaimSort)
from services.meetings import profile_fields, profile_metadata
from services.personas import revisions, sections

_CLAIM_NAMESPACE = UUID("9a9b960b-0574-53ed-9f5d-9a3f67b58fd7")
_WRITE_LOCK = "agent-smith:profile-write"
MAX_TAGS = 20
MAX_TAG_LENGTH = 100
MAX_PROFILE_NAME_LENGTH = 200
DEFAULT_PROFILE_SORT = "starred_name_asc"
PROFILE_SORTS = {
    f"{name}_{direction}": f"{column} {direction.upper()}"
    for name, column in (("name", "lower({alias}.display_name)"), ("created_at", "{alias}.created_at"), ("updated_at", "{alias}.updated_at"))
    for direction in ("asc", "desc")
}
PROFILE_SORTS[DEFAULT_PROFILE_SORT] = "{alias}.starred DESC, lower({alias}.display_name) ASC"
_CANONICAL_JOIN = """FROM participant_profiles requested JOIN participant_profiles canonical
    ON canonical.id = COALESCE(requested.merged_into, requested.id)"""


class ProfileRevisionConflict(RuntimeError):
    pass


@contextmanager
def profile_write_cursor():
    with _cursor() as cur:
        try:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            # Let the lock-specific timeout identify contention before the statement cap.
            cur.execute("SET LOCAL statement_timeout = '6s'")
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (_WRITE_LOCK,))
            cur.execute("SET LOCAL statement_timeout = '5s'")
            yield cur
        except LockNotAvailable:
            raise ProfileRevisionConflict("Profiles are busy; try again.") from None


def canonical_rows(cur, profile_ids: list[str], *, lock: bool = False, metadata_only: bool = False,
                   include_history: bool = True) -> dict[str, dict | None]:
    keys = list(dict.fromkeys(str(UUID(str(profile_id))) for profile_id in profile_ids))
    if not keys:
        return {}
    columns = "canonical.id, canonical.identity_key, canonical.display_name, canonical.email, canonical.identity_scope, canonical.merged_into, canonical.deleted, canonical.revision" if metadata_only else "canonical.*"
    if not metadata_only and not include_history:
        columns = "to_jsonb(canonical) - 'merge_history' AS profile"
    cur.execute(
        f"SELECT requested.id AS requested_id, {columns} {_CANONICAL_JOIN} WHERE requested.id IN %s"
        + (" FOR UPDATE OF canonical" if lock else ""), (tuple(keys),),
    )
    result = dict.fromkeys(keys)
    for found in cur.fetchall():
        row = dict(found)
        requested_id = str(row.pop("requested_id"))
        if not metadata_only and not include_history:
            row = row["profile"]
        if row["merged_into"] is not None:
            raise ProfileRevisionConflict("Profile identity changed; reload the canonical profile")
        result[requested_id] = row
    return result


def _canonical(cur, profile_id: str, *, lock: bool = False, include_history: bool = True) -> dict | None:
    return canonical_rows(cur, [profile_id], lock=lock, include_history=include_history)[str(UUID(profile_id))]


def canonical_identity_ids(cur, profile_id: str) -> list[str]:
    cur.execute("SELECT id::text FROM participant_profiles WHERE id=%s OR merged_into=%s ORDER BY id", (profile_id, profile_id))
    return [row["id"] for row in cur.fetchall()]


def _compact_profile(profile: dict) -> dict:
    fields = ("id", "display_name", "email", "identity_scope", "revision", "deleted", "created_at", "updated_at",
              "tags", "starred", "aliases", "emails", "nicknames", "metadata", "section_notes", "assessment", "relationships",
              "relationship_cards", "relationship_unassigned")
    result = {key: profile[key] for key in fields if key in profile}
    claims = profile["claims"]
    provenance = profile.get("metadata_provenance", {})
    meetings = {claim["meeting_id"] for claim in claims}
    meetings.update(source["meeting_id"] for source in provenance.values() if source.get("meeting_id"))
    result.update(claims=[], evidence_loaded=False, claim_count=len(claims), meeting_count=len(meetings))
    result["metadata_provenance"] = {
        key: {"human": True} if source.get("human") else {
            "meeting_id": source["meeting_id"], "evidence": [], "evidence_count": len(source.get("evidence", [])),
        }
        for key, source in provenance.items()
    }
    proof_fields = ("human", "status", "coverage", "generated_at")
    result["section_evidence"] = {
        key: {**{field: proof[field] for field in proof_fields if field in proof}, "claim_count": len(proof.get("claim_ids", []))}
        for key, proof in profile.get("section_evidence", {}).items()
    }
    return result


def _detail(cur, row: dict, *, include_evidence: bool = True) -> dict:
    if type(include_evidence) is not bool:
        raise ValueError("Profile include_evidence must be a boolean")
    if not include_evidence:
        row = {key: value for key, value in row.items() if key != "merge_history"}
    cur.execute("SELECT id, display_name, email, identity_scope FROM participant_profiles WHERE merged_into = %s ORDER BY id", (row["id"],))
    aliases = [_serialize(dict(alias)) for alias in cur.fetchall()]
    from services.meetings.relationship_db import for_profiles

    visible = _visible(cur, [row])[0]
    emails = sorted({value.strip().casefold() for value in [row.get("email"), *(alias.get("email") for alias in aliases)] if value})
    relationships = for_profiles(cur, [row], include_evidence=include_evidence)
    from services.personas.assessment_db import describe

    contexts = _source_contexts(cur, [row], {claim["meeting_id"] for claim in row["claims"] if claim.get("meeting_id")})
    result = {**visible, "aliases": aliases, "emails": emails, "relationships": relationships[str(row["id"])],
              "assessment": describe(row, sections.effective_claims(row, contexts), relationships[str(row["id"])])}
    from services.meetings.relationship_card_db import for_profile

    result.update(for_profile(cur, row, visible))
    return result if include_evidence else _compact_profile(result)


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
                or identity in identities or participant.get("identity_scope") not in {"email", "meeting", "manual"}
                or not isinstance(participant.get("display_name"), str) or not participant["display_name"].strip()
                or len(participant["display_name"]) > 1000
                or (participant.get("email") is not None and not isinstance(participant["email"], str))):
            raise ValueError("Participant identity is invalid or duplicated")
        catalog[profile_id] = {**participant, "id": profile_id}
        identities.add(identity)
    return catalog


def resolve_participants(participants: list[dict], *, cursor=None) -> list[dict]:
    catalog = _catalog(participants)
    if not catalog:
        return []
    for participant in catalog.values():
        segments = participant.get("segment_ids", [])
        if not isinstance(segments, list) or any(not isinstance(segment, str) or not segment.strip() for segment in segments):
            raise ValueError("Participant segment IDs must be nonblank strings")
    with (_cursor() if cursor is None else nullcontext(cursor)) as cur:
        known = canonical_rows(cur, list(catalog), metadata_only=True)
    resolved = {}
    for profile_id, participant in catalog.items():
        existing = known.get(profile_id)
        if existing is None and participant["identity_key"].startswith("profile:"):
            raise ProfileRevisionConflict("The selected participant profile no longer exists")
        metadata = {key: str(value) if isinstance(value, UUID) else value for key, value in (existing or {}).items() if key != "merged_into"}
        row = {**participant, **metadata}
        canonical_id = row["id"]
        current = resolved.setdefault(canonical_id, {**row, "segment_ids": []})
        for segment in participant.get("segment_ids", []):
            if segment not in current["segment_ids"]:
                current["segment_ids"].append(segment)
    return list(resolved.values())


def include_linked_profiles(participants: list[dict]) -> list[dict]:
    catalog = _catalog(participants)
    if not catalog:
        return []
    with _cursor() as cur:
        cur.execute("""SELECT DISTINCT p.* FROM profile_relationships r
            JOIN participant_profiles p ON p.id = r.subject_id OR p.id = r.target_id
            WHERE (r.subject_id IN %s OR r.target_id IN %s)
              AND NOT p.deleted AND p.merged_into IS NULL ORDER BY p.id""", (tuple(catalog), tuple(catalog)))
        for found in cur.fetchall():
            row = _serialize(dict(found))
            catalog.setdefault(row["id"], {key: row[key] for key in ("id", "identity_key", "display_name", "email", "identity_scope")} | {"segment_ids": []})
    if len(catalog) > 200:
        raise ValueError("Persona participant and relationship context exceeds 200 people")
    return list(catalog.values())


def _source_contexts(cur, rows: list[dict], meeting_ids: set[str] | None = None) -> dict[str, dict]:
    ids = profile_metadata.source_ids(rows) | sections.source_ids(rows) | (meeting_ids or set())
    if not ids:
        return {}
    cur.execute("""SELECT m.id, m.available, m.participants_revision, d.transcript_status, d.transcript_hash
        FROM meeting_summaries m LEFT JOIN meeting_digestions d ON d.meeting_id = m.id WHERE m.id IN %s""", (tuple(ids),))
    return {str(row["id"]): dict(row) for row in cur.fetchall()}


def _visible(cur, rows: list[dict], *, include_overrides: bool = False) -> list[dict]:
    meeting_ids = {claim.get("meeting_id") for row in rows for claim in row["claims"] if claim.get("meeting_id")}
    contexts = _source_contexts(cur, rows, meeting_ids)
    result = []
    for row in rows:
        claims = []
        for claim in row["claims"]:
            if profile_metadata.claim_source_valid(claim, contexts) and not claim.get("superseded"):
                claims.append(claim)
            elif include_overrides and claim.get("status") in {"corrected", "rejected"}:
                claims.append({**claim, "evidence": [], "source_url": None, "rationale": "", "source_unavailable": True})
        projected = sections.project(profile_metadata.project(row, contexts), sections.effective_claims(row, contexts), contexts)
        result.append(_serialize({**projected, "claims": claims}))
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
            if existing and (existing["merged_into"] is not None or existing["identity_key"] != participant["identity_key"]):
                raise ProfileRevisionConflict("Participant identity changed")
            result.append(existing or {
                **{key: participant.get(key) for key in ("id", "identity_key", "display_name", "email", "identity_scope")},
                "claims": [], "revision": 0, "deleted": False, "created_at": None, "updated_at": None,
                "tags": [], "starred": False, "merged_into": None, "merge_history": [],
                "metadata": {}, "metadata_provenance": {}, "section_notes": {}, "section_evidence": {}, "nicknames": [],
            })
        from services.meetings.relationship_db import for_profiles

        visible = _visible(cur, result, include_overrides=True)
        relationships = for_profiles(cur, result, include_dismissed=True, include_overrides=True)
        return [{**row, "relationships": relationships[row["id"]]} for row in visible]


def get_profile(profile_id: str, *, include_evidence: bool = True) -> dict | None:
    with _cursor() as cur:
        row = _canonical(cur, profile_id, include_history=include_evidence)
        return _detail(cur, row, include_evidence=include_evidence) if row and not row["deleted"] else None


def list_claims(profile_id: str, *, limit: int = 20, offset: int = 0, query: str | None = None,
                category: ProfileCategory | None = None, epistemic: ProfileEpistemic | None = None,
                confidence: ProfileConfidence | None = None, status: ProfileReviewStatus | None = None,
                target_id: str | None = None, sort: ProfileClaimSort = "oldest") -> dict | None:
    key = str(UUID(profile_id))
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("Profile claim limit must be 1-100 and offset must be nonnegative")
    filters, params = [], [key]
    for field, value, choices in (("category", category, ProfileCategory), ("epistemic", epistemic, ProfileEpistemic),
                                   ("confidence", confidence, ProfileConfidence), ("status", status, ProfileReviewStatus)):
        if value is not None:
            if not isinstance(value, str) or value not in get_args(choices):
                raise ValueError(f"Profile evidence {field} is invalid")
            filters.append(f"value->>'{field}' = %s")
            params.append(value)
    if not isinstance(sort, str) or sort not in get_args(ProfileClaimSort):
        raise ValueError("Profile evidence sort must be oldest or newest")
    if query is not None:
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError("Profile evidence query must be nonblank and at most 1000 characters")
        filters.append("""concat_ws(' ', value->>'content', value->'correction'->>'content',
            value->'correction'->>'reason', value->>'rationale', value->'evidence', meeting_title) ILIKE %s""")
        params.append("%" + query.strip() + "%")
    if target_id is not None:
        filters.append("canonical_target_id = (SELECT coalesce(merged_into,id) FROM participant_profiles WHERE id=%s AND NOT deleted)")
        params.append(str(UUID(str(target_id))))
    where = " AND ".join(filters) or "true"
    direction = "DESC" if sort == "newest" else "ASC"
    with _cursor() as cur:
        cur.execute(f"""WITH profile AS (
                SELECT canonical.id, canonical.revision, canonical.deleted, canonical.merged_into, canonical.claims
                {_CANONICAL_JOIN} WHERE requested.id = %s
            ), visible AS (
                SELECT claim.value, claim.ordinality, meeting.title AS meeting_title,
                    meeting.provider_created_at AS meeting_date,
                    CASE WHEN NOT target.deleted AND NOT canonical_target.deleted THEN canonical_target.id END AS canonical_target_id,
                    CASE WHEN NOT canonical_target.deleted THEN canonical_target.display_name END AS canonical_target_name
                FROM profile
                CROSS JOIN LATERAL jsonb_array_elements(profile.claims) WITH ORDINALITY claim(value, ordinality)
                JOIN meeting_summaries meeting ON meeting.id=(claim.value->>'meeting_id')::uuid
                LEFT JOIN participant_profiles target ON target.id=(claim.value->>'target_id')::uuid
                LEFT JOIN participant_profiles canonical_target ON canonical_target.id=coalesce(target.merged_into,target.id)
                WHERE NOT profile.deleted AND profile.merged_into IS NULL
                  AND claim.value->>'superseded' IS DISTINCT FROM 'true'
                  AND {profile_metadata.source_sql('claim.value', legacy_claim=True)}
            ), filtered AS (
                SELECT value || jsonb_build_object('meeting_title',meeting_title,'meeting_date',meeting_date)
                    || CASE WHEN canonical_target_id IS NOT NULL THEN jsonb_build_object(
                        'target_id',canonical_target_id,'target_name',canonical_target_name)
                        WHEN value->>'target_id' IS NOT NULL THEN jsonb_build_object('target_id',NULL,'target_name',NULL)
                        ELSE '{{}}'::jsonb END AS value,
                    ordinality FROM visible WHERE {where}
            ) SELECT profile.id AS profile_id, profile.revision, profile.deleted, profile.merged_into,
                (SELECT count(*) FROM filtered) AS total,
                coalesce((SELECT jsonb_agg(page.value ORDER BY page.ordinality {direction}) FROM (
                    SELECT value, ordinality FROM filtered ORDER BY ordinality {direction} LIMIT %s OFFSET %s
                ) page), '[]'::jsonb) AS items FROM profile""", (*params, limit, offset))
        row = cur.fetchone()
        if row is None or row["deleted"]:
            return None
        if row["merged_into"] is not None:
            raise ProfileRevisionConflict("Profile identity changed; reload the canonical profile")
        return _serialize({key: row[key] for key in ("profile_id", "revision", "items", "total")})


def _profile_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_PROFILE_NAME_LENGTH:
        raise ValueError(f"Profile name must be nonblank and at most {MAX_PROFILE_NAME_LENGTH} characters")
    return value.strip()


def _email_matches(cur, identity: dict) -> list[dict]:
    cur.execute("""SELECT id, deleted FROM participant_profiles
                   WHERE id = %s OR identity_key = %s OR lower(email) = %s ORDER BY id FOR UPDATE""",
                (identity["id"], identity["identity_key"], identity["email"]))
    return [dict(found) for found in cur.fetchall()]


def create_profile(display_name: str, email: str | None = None, *, include_evidence: bool = True) -> dict:
    from services.meetings.participants import email_participant

    name = _profile_name(display_name)
    if email is not None:
        identity = email_participant(email, name)
    else:
        profile_id = str(uuid4())
        identity = {"id": profile_id, "identity_key": "manual:" + profile_id,
                    "display_name": name, "email": None, "identity_scope": "manual"}
    with profile_write_cursor() as cur:
        if email is not None and _email_matches(cur, identity):
            raise ProfileRevisionConflict("A profile already uses this email; open or merge the existing profile")
        cur.execute(
            """INSERT INTO participant_profiles (id, identity_key, display_name, email, identity_scope)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            tuple(identity[key] for key in ("id", "identity_key", "display_name", "email", "identity_scope")),
        )
        row = dict(cur.fetchone())
        revisions.record(cur, None, row, actor="human", source="manual")
        return _detail(cur, row, include_evidence=include_evidence)


def _tags(tags: list[str]) -> list[str]:
    if not isinstance(tags, list) or len(tags) > MAX_TAGS:
        raise ValueError(f"Profile tags must contain at most {MAX_TAGS} strings")
    normalized = []
    for tag in tags:
        if not isinstance(tag, str) or not tag.strip() or len(tag.strip()) > MAX_TAG_LENGTH:
            raise ValueError(f"Profile tags must be nonblank strings of at most {MAX_TAG_LENGTH} characters")
        if tag.strip() not in normalized:
            normalized.append(tag.strip())
    return normalized


def list_profiles(query: str | None = None, limit: int = 20, offset: int = 0, *,
                  tags: list[str] | None = None, starred: bool | None = None, sort: str = DEFAULT_PROFILE_SORT) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("Profile limit must be 1-100 and offset must be nonnegative")
    if not isinstance(sort, str) or sort not in PROFILE_SORTS:
        raise ValueError("Profile sort must select starred_name_asc, name, created_at or updated_at with asc or desc")
    if starred is not None and type(starred) is not bool:
        raise ValueError("Profile starred filter must be a boolean")
    normalized_tags = _tags(tags) if tags is not None else []
    clauses, params = ["NOT p.deleted", "p.merged_into IS NULL"], []
    if query is not None:
        if not isinstance(query, str) or not query.strip() or len(query) > 1000:
            raise ValueError("Profile query must be nonblank and at most 1000 characters")
        clauses.append(f"""(p.display_name ILIKE %s OR p.email ILIKE %s OR EXISTS (
            SELECT 1 FROM participant_profiles alias WHERE alias.merged_into = p.id
            AND (alias.email ILIKE %s OR alias.display_name ILIKE %s))
            OR EXISTS (SELECT 1 FROM unnest(p.nicknames) nickname WHERE nickname ILIKE %s)
            OR ({profile_metadata.visible_sql('p')})->>'company' ILIKE %s
            OR ({profile_metadata.visible_sql('p')})->>'job_role' ILIKE %s)""")
        params.extend([f"%{query.strip()}%"] * 7)
    if normalized_tags:
        clauses.append("p.tags @> %s::text[]")
        params.append(normalized_tags)
    if starred is not None:
        clauses.append("p.starred = %s")
        params.append(starred)
    where = " AND ".join(clauses)
    order = PROFILE_SORTS[sort]
    with _cursor() as cur:
        cur.execute(f"SELECT count(*) AS count FROM participant_profiles p WHERE {where}", params)
        total = cur.fetchone()["count"]
        cur.execute(
            f"""SELECT page.id, page.display_name, page.email, page.identity_scope, page.revision,
                   page.created_at, page.updated_at, page.tags, page.starred,
                   {profile_metadata.visible_sql('page')} AS metadata, page.nicknames,
                   ARRAY(SELECT DISTINCT lower(identity.email) FROM participant_profiles identity
                         WHERE (identity.id = page.id OR identity.merged_into = page.id) AND identity.email IS NOT NULL
                         ORDER BY lower(identity.email)) AS emails,
                   visible.claim_count, visible.meeting_count
               FROM (
                   SELECT p.* FROM participant_profiles p WHERE {where}
                   ORDER BY {order.format(alias='p')}, p.id ASC LIMIT %s OFFSET %s
               ) page CROSS JOIN LATERAL (
                   WITH claim_sources AS (
                       SELECT claim->>'meeting_id' AS id FROM jsonb_array_elements(page.claims) claim
                       WHERE claim->>'superseded' IS DISTINCT FROM 'true'
                         AND {profile_metadata.source_sql('claim', legacy_claim=True)}
                   )
                   SELECT (SELECT count(*) FROM claim_sources) AS claim_count,
                          (SELECT count(*) FROM (
                              SELECT id FROM claim_sources UNION
                              SELECT source.value->>'meeting_id' FROM jsonb_each(page.metadata_provenance) source
                              WHERE page.metadata ? source.key AND source.value->>'human' IS DISTINCT FROM 'true'
                                AND {profile_metadata.source_sql('source.value')}
                          ) meeting_sources) AS meeting_count
               ) visible ORDER BY {order.format(alias='page')}, page.id ASC""",
            (*params, limit, offset),
        )
        return {"items": [_serialize(dict(row)) for row in cur.fetchall()], "total": total}


def save_progress(meeting_id: str, owner: str, transcript_hash: str, artifact: dict) -> None:
    stage_db.save_progress("profile", meeting_id, owner, transcript_hash, artifact)


def record_failure(meeting_id: str, owner: str, error_type: str) -> None:
    stage_db.record_failure("profile", meeting_id, owner, error_type)


def reset_progress(meeting_id: str, owner: str, transcript_hash: str) -> None:
    save_progress(meeting_id, owner, transcript_hash, {})


def _validated_outputs(candidates: list, schema, catalog: dict[str, dict], record: dict) -> list[dict]:
    if not isinstance(candidates, list):
        raise ValueError("Profile output items must be an array")
    segments = {item["id"]: item["text"] for item in record["transcript"]["segments"]}
    result = []
    for item in candidates:
        try:
            item = schema.model_validate(item).model_dump()
        except ValidationError:
            raise ValueError("Profile output does not match the output schema") from None
        subject, target = item["subject_id"], item.get("target_id")
        if subject not in catalog or (target is not None and target not in catalog):
            raise ValueError("Profile claim references an unknown participant")
        evidence = item["evidence"]
        allowed = catalog[subject].get("segment_ids", [])
        if any(entry["segment_id"] not in allowed or not entry["quote"].strip()
               or entry["quote"] not in segments.get(entry["segment_id"], "") for entry in evidence):
            raise ValueError("Profile claim requires exact evidence from its subject")
        result.append(item)
    return result


def _validate_candidates(artifact: dict, catalog: dict[str, dict], record: dict) -> list[dict]:
    expected = artifact.get("expected_revisions")
    if not isinstance(expected, dict) or set(expected) != set(catalog) or any(type(value) is not int or value < 0 for value in expected.values()):
        raise ValueError("Profile output requires every participant revision")
    claims = []
    for item in _validated_outputs(artifact.get("items"), ProfileClaim, catalog, record):
        target = item["target_id"]
        claims.append({
            **item,
            "meeting_id": str(record["meeting_id"]), "source_url": record["snapshot"]["source_url"],
            "transcript_hash": record["transcript_hash"],
            "participants_revision": record.get("participants_revision", 0),
            "target_name": catalog[target]["display_name"] if target else None,
            "status": "active", "correction": None,
        })
    return claims


def _claim_identity(claim: dict, canonical_ids: dict[str, str]) -> str:
    subject, target = claim["subject_id"], claim.get("target_id")
    return json.dumps({
        "meeting_id": claim["meeting_id"], "subject_id": canonical_ids.get(subject, subject),
        "target_id": canonical_ids.get(target, target), "category": claim["category"],
        "content": profile_fields.normalized_text(claim["content"]),
        "evidence": sorted({(entry["segment_id"], entry["quote"]) for entry in claim["evidence"]}),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _cumulative_claims(existing: list[dict], candidates: list[dict], canonical_ids: dict[str, str]) -> list[dict]:
    cumulative = copy.deepcopy(existing)
    identities = {}
    for index, claim in enumerate(cumulative):
        identities.setdefault(_claim_identity(claim, canonical_ids), index)
    for claim in candidates:
        identity = _claim_identity(claim, canonical_ids)
        if identity in identities:
            stored = cumulative[identities[identity]]
            if stored.get("superseded"):
                stored["superseded"] = False
            continue
        claim = {**claim, "id": str(uuid5(_CLAIM_NAMESPACE, identity))}
        if any(stored["id"] == claim["id"] for stored in cumulative):
            raise ProfileRevisionConflict("A profile claim identity conflicts with existing evidence")
        identities[identity] = len(cumulative)
        cumulative.append(claim)
    _validate_claim_size(cumulative)
    return cumulative


def apply_profiles(meeting_id: str, owner: str, transcript_hash: str, artifact: dict, participants: list[dict]) -> list[str]:
    stage_db.validate_artifact(artifact)
    catalog = _catalog(participants)
    with profile_write_cursor() as cur:
        record = stage_db.pending(cur, meeting_id, owner, transcript_hash, "profile")
        control = record.get("manual_analysis", {}).get("profile", {})
        manual_target = (control.get("target") or {}).get("id") if control.get("active") else None
        if record.get("participants_revision", 0) != artifact.get("participants_revision", 0):
            raise ProfileRevisionConflict("Meeting participants changed; rebuild the profile candidate")
        claims = _validate_candidates(artifact, catalog, record)
        metadata_updates = _validated_outputs(artifact.get("metadata_updates", []), ProfileMetadataPatch, catalog, record)
        if manual_target and any(item["subject_id"] != manual_target for item in [*claims, *metadata_updates]):
            raise ProfileRevisionConflict("Manual analysis may only publish changes to the selected target profile")
        rows = {}
        if catalog:
            cur.execute("SELECT * FROM participant_profiles WHERE id IN %s ORDER BY id FOR UPDATE", (tuple(catalog),))
            rows = {str(row["id"]): dict(row) for row in cur.fetchall()}
        for profile_id in sorted(catalog):
            row = rows.get(profile_id)
            if ((row["revision"] if row else 0) != artifact["expected_revisions"][profile_id]
                    or (row and (row["merged_into"] is not None or row["identity_key"] != catalog[profile_id]["identity_key"]))):
                raise ProfileRevisionConflict("Participant profile changed; rebuild the profile candidate")
        contexts = _source_contexts(cur, list(rows.values()))
        all_claims = claims + [claim for row in rows.values() for claim in row["claims"]]
        identity_ids = {claim[key] for claim in all_claims for key in ("subject_id", "target_id") if claim.get(key)}
        canonical_ids = {key: str(row["id"]) if row else key
                         for key, row in canonical_rows(cur, list(identity_ids), metadata_only=True).items()}
        for claim in claims:
            if any(rows.get(profile_id, {}).get("deleted") for profile_id in (claim["subject_id"], claim["target_id"])):
                raise ProfileRevisionConflict("A participant profile was deleted")
            if any(prior.get("status") in {"corrected", "rejected"}
                   and profile_fields.normalized_text(prior["content"]) == profile_fields.normalized_text(claim["content"])
                   and _claim_identity(prior, canonical_ids) != _claim_identity(claim, canonical_ids)
                   for prior in rows.get(claim["subject_id"], {}).get("claims", [])):
                raise ProfileRevisionConflict("This assertion was corrected or rejected; honor the human correction")
        if catalog:
            cur.execute("SELECT subject_id, target_id FROM profile_relationships WHERE dismissed AND subject_id IN %s", (tuple(catalog),))
            dismissed = {(str(row["subject_id"]), str(row["target_id"])) for row in cur.fetchall()}
            if any((claim["subject_id"], claim.get("target_id")) in dismissed for claim in claims):
                raise ProfileRevisionConflict("This relationship was removed; honor the human correction")
        applied = []
        affected = ({claim[key] for claim in claims for key in ("subject_id", "target_id") if claim.get(key)}
                    | {patch["subject_id"] for patch in metadata_updates})
        if manual_target:
            affected &= {manual_target}
        for profile_id in sorted(affected):
            additions = [claim for claim in claims if claim["subject_id"] == profile_id]
            row = rows.get(profile_id)
            if row and row["deleted"]:
                raise ProfileRevisionConflict("A participant profile was deleted")
            cumulative = _cumulative_claims(row["claims"] if row else [], additions, canonical_ids)
            metadata, provenance = profile_metadata.fill_missing(row or {},
                [patch for patch in metadata_updates if patch["subject_id"] == profile_id], record, contexts)
            metadata_changed = (metadata, provenance) != ((row or {}).get("metadata", {}), (row or {}).get("metadata_provenance", {}))
            if row:
                if cumulative != row["claims"] or metadata_changed:
                    cur.execute("""UPDATE participant_profiles SET claims = %s, metadata = %s, metadata_provenance = %s,
                                assessment_dirty = true, assessment_attempts = 0, assessment_error = NULL,
                                assessment_next_attempt_at = now(), revision = revision + 1, updated_at = clock_timestamp()
                                WHERE id = %s RETURNING *""",
                                (Json(cumulative), Json(metadata), Json(provenance), profile_id))
                    revisions.record(cur, row, dict(cur.fetchone()), actor="agent", source="meeting", source_id=meeting_id)
            else:
                participant = catalog[profile_id]
                cur.execute(
                    """INSERT INTO participant_profiles (id, identity_key, display_name, email, identity_scope, claims, metadata, metadata_provenance)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING *""",
                    (profile_id, participant["identity_key"], participant["display_name"], participant.get("email"), participant["identity_scope"],
                     Json(cumulative), Json(metadata), Json(provenance)),
                )
                created = cur.fetchone()
                if not created:
                    raise ProfileRevisionConflict("Participant identity was created concurrently")
                revisions.record(cur, None, dict(created), actor="agent", source="meeting", source_id=meeting_id)
            if additions or metadata_changed:
                applied.append(profile_id)
        from services.meetings.relationship_db import ensure_claim_links

        links = [{**claim, "subject_id": canonical_ids.get(claim["subject_id"], claim["subject_id"]),
                  "target_id": canonical_ids.get(claim.get("target_id"), claim.get("target_id"))} for claim in all_claims]
        if manual_target:
            links = [claim for claim in links if claim["subject_id"] == manual_target and claim.get("target_id") in rows]
        ensure_claim_links(cur, links)
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
    row = _canonical(cur, profile_id, lock=True)
    if row is None or row["deleted"]:
        raise ValueError("Participant profile does not exist")
    if row["revision"] != expected_revision:
        raise ProfileRevisionConflict("Participant profile changed; reload before editing")
    return row


def correct_claim(profile_id: str, claim_id: str, expected_revision: int, action: str, content: str | None, reason: str,
                  *, include_evidence: bool = True) -> dict:
    UUID(profile_id)
    UUID(claim_id)
    _expected_revision(expected_revision)
    if (action not in {"correct", "reject"} or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000
            or (action == "correct" and (not isinstance(content, str) or not content.strip() or len(content) > 2000))):
        raise ValueError("Claim correction requires a supported action, reason and corrected content")
    with profile_write_cursor() as cur:
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
        cur.execute("UPDATE participant_profiles SET claims = %s, assessment_dirty = true, assessment_attempts = 0, assessment_error = NULL, assessment_next_attempt_at = now(), revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s RETURNING *",
                    (Json(claims), row["id"]))
        updated = dict(cur.fetchone())
        revisions.record(cur, row, updated, actor="human", source="manual")
        return _detail(cur, updated, include_evidence=include_evidence)


def delete_profile(profile_id: str, expected_revision: int) -> None:
    UUID(profile_id)
    _expected_revision(expected_revision)
    with profile_write_cursor() as cur:
        row = _editable(cur, profile_id, expected_revision)
        cur.execute("UPDATE participant_profiles SET claims = '[]'::jsonb, deleted = true, assessment_dirty = false, assessment_claim_owner = NULL, assessment_claim_until = NULL, revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s RETURNING *", (row["id"],))
        revisions.record(cur, row, dict(cur.fetchone()), actor="human", source="manual")


def update_metadata(profile_id: str, expected_revision: int, *, display_name: str | None = None,
                    tags: list[str] | None = None, starred: bool | None = None,
                    metadata: dict | None = None, nicknames: list[str] | None = None,
                    section_notes: dict | None = None, allow_agent_sections: list[str] | None = None,
                    include_evidence: bool = True) -> dict:
    _expected_revision(expected_revision)
    if all(value is None for value in (display_name, tags, starred, metadata, nicknames, section_notes, allow_agent_sections)):
        raise ValueError("Provide profile fields to update")
    normalized_name = _profile_name(display_name) if display_name is not None else None
    normalized_tags = _tags(tags) if tags is not None else None
    normalized_metadata = profile_fields.fields(metadata, profile_fields.METADATA_FIELDS, "metadata") if metadata is not None else None
    normalized_notes = profile_fields.fields(section_notes, profile_fields.SECTION_FIELDS, "section_notes") if section_notes is not None else None
    normalized_nicknames = profile_fields.nicknames(nicknames) if nicknames is not None else None
    if allow_agent_sections is not None and (not isinstance(allow_agent_sections, list)
            or any(not isinstance(key, str) or key not in profile_fields.SECTION_FIELDS for key in allow_agent_sections)):
        raise ValueError("Only known profile sections can allow automatic updates")
    if starred is not None and type(starred) is not bool:
        raise ValueError("Profile starred state must be a boolean")
    with profile_write_cursor() as cur:
        row = _editable(cur, profile_id, expected_revision)
        new_tags = normalized_tags if normalized_tags is not None else row["tags"]
        new_starred = starred if starred is not None else row["starred"]
        new_name = normalized_name if normalized_name is not None else row["display_name"]
        new_metadata, new_provenance = profile_metadata.human_patch(row, normalized_metadata) if normalized_metadata is not None else (row["metadata"], row["metadata_provenance"])
        new_notes, new_evidence = sections.human_patch(row, normalized_notes, allow_agent_sections or [])
        new_nicknames = normalized_nicknames if normalized_nicknames is not None else row["nicknames"]
        before = (row["display_name"], row["tags"], row["starred"], row["metadata"], row["section_notes"], row["nicknames"], row["metadata_provenance"], row["section_evidence"])
        after = (new_name, new_tags, new_starred, new_metadata, new_notes, new_nicknames, new_provenance, new_evidence)
        if before != after:
            semantic = any(before[index] != after[index] for index in (0, 3, 4, 5, 6, 7))
            cur.execute(
                """UPDATE participant_profiles SET display_name = %s, tags = %s, starred = %s,
                   metadata = %s, section_notes = %s, nicknames = %s, metadata_provenance = %s, section_evidence = %s,
                   assessment_dirty = assessment_dirty OR %s,
                   assessment_attempts = CASE WHEN %s THEN 0 ELSE assessment_attempts END,
                   assessment_error = CASE WHEN %s THEN NULL ELSE assessment_error END,
                   assessment_next_attempt_at = CASE WHEN %s THEN now() ELSE assessment_next_attempt_at END, revision = revision + 1,
                   updated_at = clock_timestamp() WHERE id = %s RETURNING *""",
                (new_name, new_tags, new_starred, Json(new_metadata), Json(new_notes), new_nicknames, Json(new_provenance), Json(new_evidence), semantic, semantic, semantic, semantic, row["id"]),
            )
            updated = dict(cur.fetchone())
            revisions.record(cur, row, updated, actor="human", source="manual")
            row = updated
        return _detail(cur, row, include_evidence=include_evidence)


def _attributes(row: dict) -> dict:
    return {key: row[key] for key in ("display_name", "email", "identity_scope", "tags", "starred", "metadata", "section_notes", "section_evidence", "nicknames", "metadata_provenance")}


def _merge_claims(target: list[dict], source: list[dict]) -> tuple[list[dict], list[str]]:
    combined = {}
    for claim in target + source:
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not claim_id:
            raise ValueError("Profile claims require stable IDs")
        if claim_id in combined and combined[claim_id] != claim:
            raise ProfileRevisionConflict("Profiles contain different versions of the same claim; resolve the conflict before merging")
        combined[claim_id] = claim
    _validate_claim_size(list(combined.values()))
    existing_ids = {claim["id"] for claim in target}
    return list(combined.values()), list(dict.fromkeys(claim["id"] for claim in source if claim["id"] not in existing_ids))


def merge_profiles(source_id: str, target_id: str, expected_revision: int, target_revision: int,
                   *, include_evidence: bool = True) -> dict:
    _expected_revision(expected_revision)
    _expected_revision(target_revision)
    with profile_write_cursor() as cur:
        source = _editable(cur, source_id, expected_revision)
        target = _editable(cur, target_id, target_revision)
        if source["id"] == target["id"]:
            raise ValueError("Select two different canonical profiles to merge")
        claims, moved_ids = _merge_claims(target["claims"], source["claims"])
        tags = _tags(list(dict.fromkeys(target["tags"] + source["tags"])))
        history = target["merge_history"] + source["merge_history"] + [{
            "action": "merge", "source_id": str(source["id"]), "target_id": str(target["id"]),
            "source_revision": source["revision"], "target_revision": target["revision"],
            "timestamp": datetime.now(timezone.utc).isoformat(), "moved_claim_ids": moved_ids,
            "previous_source": _attributes(source), "previous_target": _attributes(target),
        }]
        email = target["email"] or source["email"]
        metadata, provenance = profile_metadata.merge(source, target, _source_contexts(cur, [source, target]))
        section_notes, section_evidence = {}, {}
        for key in profile_fields.SECTION_FIELDS:
            chosen = next((row for row in (target, source) if sections.human(key, row)), None)
            if chosen is None:
                chosen = target if key in target["section_notes"] else source
            if key in chosen["section_notes"]:
                section_notes[key] = chosen["section_notes"][key]
            if key in chosen["section_evidence"]:
                section_evidence[key] = chosen["section_evidence"][key]
        nicknames = profile_fields.nicknames(list(dict.fromkeys(target["nicknames"] + source["nicknames"])))
        cur.execute(
            """UPDATE participant_profiles SET claims = %s, tags = %s, starred = %s, email = %s,
               identity_scope = %s, merge_history = %s, revision = %s, metadata = %s, section_notes = %s,
               nicknames = %s, metadata_provenance = %s, section_evidence = %s,
               assessment_dirty = true, assessment_attempts = 0, assessment_error = NULL,
               assessment_next_attempt_at = now(), updated_at = clock_timestamp()
               WHERE id = %s RETURNING *""",
            (Json(claims), tags, target["starred"] or source["starred"], email, "email" if email else target["identity_scope"],
             Json(history), max(source["revision"], target["revision"]) + 1, Json(metadata), Json(section_notes), nicknames, Json(provenance), Json(section_evidence), target["id"]),
        )
        winner = dict(cur.fetchone())
        revisions.record(cur, target, winner, actor="human", source="merge", source_id=str(source["id"]))
        from services.meetings.relationship_db import merge_profile_links

        merge_profile_links(cur, str(source["id"]), str(target["id"]))
        cur.execute(
            """UPDATE participant_profiles SET claims = '[]'::jsonb, merged_into = %s, assessment_dirty = false,
               assessment_claim_owner = NULL, assessment_claim_until = NULL,
               revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s OR merged_into = %s""",
            (target["id"], source["id"], source["id"]),
        )
        revisions.record(cur, source, {**source, "claims": [], "merged_into": target["id"], "revision": source["revision"] + 1},
                         actor="human", source="merge", source_id=str(target["id"]))
        return _detail(cur, winner, include_evidence=include_evidence)


def link_alias(profile_id: str, email: str, expected_revision: int, *, include_evidence: bool = True) -> dict:
    from services.meetings.participants import email_participant

    _expected_revision(expected_revision)
    with profile_write_cursor() as cur:
        row = _editable(cur, profile_id, expected_revision)
        alias = email_participant(email, row["display_name"])
        existing = _email_matches(cur, alias)
        if existing:
            owners = canonical_rows(cur, [str(found["id"]) for found in existing], lock=True)
            if any(found["deleted"] or owners[str(found["id"])]["deleted"] or owners[str(found["id"])]["id"] != row["id"] for found in existing):
                raise ProfileRevisionConflict("This email belongs to another or deleted profile; merge existing profiles instead of linking it")
            return _detail(cur, row, include_evidence=include_evidence)
        cur.execute(
            """INSERT INTO participant_profiles (id, identity_key, display_name, email, identity_scope, merged_into)
               VALUES (%s, %s, %s, %s, 'email', %s)""",
            (alias["id"], alias["identity_key"], alias["display_name"], alias["email"], row["id"]),
        )
        history = row["merge_history"] + [{
            "action": "link_alias", "alias_id": alias["id"], "email": alias["email"], "target_id": str(row["id"]),
            "target_revision": row["revision"], "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous_target": _attributes(row),
        }]
        cur.execute(
            """UPDATE participant_profiles SET email = COALESCE(email, %s), identity_scope = 'email',
               merge_history = %s, assessment_dirty = true, assessment_attempts = 0, assessment_error = NULL,
               assessment_next_attempt_at = now(), revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s RETURNING *""",
            (alias["email"], Json(history), row["id"]),
        )
        updated = dict(cur.fetchone())
        revisions.record(cur, row, updated, actor="human", source="manual",
                         extra={"emails": {"before": None, "after": {"added": [alias["email"]]}}})
        return _detail(cur, updated, include_evidence=include_evidence)


def meeting_profiles(meeting_id: str) -> dict | None:
    UUID(meeting_id)
    with _cursor() as cur:
        cur.execute(
            f"""SELECT d.meeting_id, d.transcript_status, d.profile_status, d.profile_artifact,
               d.profile_error, d.profile_attempts, d.profile_next_attempt_at,
               {stage_db.TOTAL_UNITS_SQL} AS total_units,
               d.profile_claim_until > clock_timestamp() AS running FROM meeting_summaries m
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
                    cur.execute(
                        f"""SELECT DISTINCT canonical.id, canonical.display_name, canonical.email, canonical.revision
                            {_CANONICAL_JOIN} WHERE requested.id IN %s AND NOT canonical.deleted
                            ORDER BY canonical.display_name, canonical.id""", (tuple(ids),),
                    )
                    items = [dict(item) for item in cur.fetchall()]
            elif row["transcript_status"] != "ready":
                status, reason = "blocked", "transcript_" + row["transcript_status"]
            elif row["running"]:
                status = "running"
        return _serialize({"status": status, "items": items, "reason": reason, "error_type": row["profile_error"],
                           "progress": stage_db.progress(row, "profile", total_units=row["total_units"])})


def retry_profiles(meeting_id: str) -> None:
    from services.meetings import manual_stage

    UUID(meeting_id)
    with profile_write_cursor() as cur:
        cur.execute("SELECT * FROM meeting_digestions WHERE meeting_id=%s FOR UPDATE", (meeting_id,))
        row = cur.fetchone()
        if row and manual_stage.resume_stage(cur, dict(row), "profile"):
            return
        cur.execute(
            """UPDATE meeting_digestions d SET profile_status = 'pending', profile_attempts = 0,
               profile_next_attempt_at = clock_timestamp(), profile_error = NULL, profile_updated_at = clock_timestamp(),
               requested_at = coalesce(requested_at, clock_timestamp())
               FROM meeting_summaries m WHERE d.meeting_id = m.id AND m.available AND d.meeting_id = %s
               AND d.profile_status = 'failed' AND d.transcript_status = 'ready'
               AND coalesce(d.profile_claim_until <= clock_timestamp(), true)""", (meeting_id,),
        )
        if cur.rowcount != 1:
            raise ValueError("Meeting profiles cannot be retried in their current state")
