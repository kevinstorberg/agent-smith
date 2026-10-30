from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

from psycopg2.extras import Json

from services.meetings import profile_db, profile_fields, relationship_db
from services.meetings.profile_metadata import source_sql
from services.meetings.db import _cursor
from services.meetings.db import _serialize
from services.personas import revisions, sections

MAX_ATTEMPTS = 3
LEASE_SECONDS = 600
_DUE = f"""(assessment_dirty OR EXISTS (SELECT 1 FROM jsonb_each(section_evidence) proof
    CROSS JOIN LATERAL jsonb_array_elements(coalesce(proof.value->'sources', '[]'::jsonb)) proof_source
    WHERE proof.key!='relationships' AND proof.value->>'human' IS DISTINCT FROM 'true' AND NOT {source_sql('proof_source.value')})
    OR EXISTS (SELECT 1 FROM profile_relationships edge CROSS JOIN LATERAL
        jsonb_array_elements(coalesce(edge.analysis_evidence->'sources','[]'::jsonb)) source
        WHERE edge.subject_id=participant_profiles.id AND NOT edge.dismissed
          AND EXISTS (SELECT 1 FROM participant_profiles target WHERE target.id=edge.target_id AND NOT target.deleted AND target.merged_into IS NULL)
          AND edge.analysis_evidence->>'human' IS DISTINCT FROM 'true' AND NOT {source_sql('source.value')}))"""


def _snapshot(cur, row: dict) -> tuple[dict, list[dict]]:
    from services.meetings.relationship_db import for_profiles

    contexts = profile_db._source_contexts(cur, [row], {claim["meeting_id"] for claim in row["claims"] if claim.get("meeting_id")})
    claims = sections.effective_claims(row, contexts)
    targets = profile_db.canonical_rows(cur, [claim["target_id"] for claim in claims if claim.get("target_id")], metadata_only=True)
    claims = [{**claim, "canonical_target_id": str(targets[claim["target_id"]]["id"]) if targets.get(claim.get("target_id")) else claim.get("target_id")} for claim in claims]
    visible = profile_db._visible(cur, [row], include_overrides=True)[0]
    visible["_card_owner_ids"] = profile_db.canonical_identity_ids(cur, str(row["id"]))
    visible["relationships"] = for_profiles(cur, [row], include_dismissed=True, include_overrides=True,
                                             include_unavailable=True, include_card_state=True)[str(row["id"])]
    return visible, claims


def describe(row: dict, claims: list[dict], relationships: list[dict] | None = None) -> dict:
    current = {claim["id"]: claim["signature"] for claim in claims}
    stale = any(proof.get("status") == "supported" and not proof.get("human")
                and (not proof.get("claim_ids") or any(current.get(key) != proof.get("claim_signatures", {}).get(key)
                                                       for key in proof["claim_ids"]))
                for key, proof in row.get("section_evidence", {}).items() if key != "relationships")
    stale |= any(edge.get("analysis_stale") for edge in relationships or [] if edge["subject_id"] == str(row["id"]))
    running = row.get("assessment_claim_owner") is not None and row.get("assessment_claim_until") is not None
    if running:
        until = row["assessment_claim_until"]
        running = datetime.fromisoformat(until) > datetime.now(timezone.utc) if isinstance(until, str) else until > datetime.now(timezone.utc)
    state = "running" if running else "failed" if row.get("assessment_error") else "pending" if row.get("assessment_dirty", True) or stale else "current"
    if state == "current" and not any(row.get("section_notes", {}).values()):
        state = "insufficient_evidence"
    return _serialize({"status": state, "attempts": row.get("assessment_attempts", 0),
            "next_attempt_at": row.get("assessment_next_attempt_at"), "error": row.get("assessment_error"),
            "coverage": sections.coverage(claims), "can_generate": bool(claims)})


def has_requested_work(profile_id: str | None = None) -> bool:
    with _cursor() as cur:
        cur.execute(f"""SELECT EXISTS (SELECT 1 FROM participant_profiles
            WHERE {_DUE} AND NOT deleted AND merged_into IS NULL
              AND assessment_attempts < %s AND assessment_next_attempt_at <= now()
              AND (assessment_claim_until IS NULL OR assessment_claim_until <= now())
              AND (%s::uuid IS NULL OR id = %s::uuid)) AS found""", (MAX_ATTEMPTS, profile_id, profile_id))
        return cur.fetchone()["found"]


def claim(owner: str, profile_id: str | None = None) -> dict | None:
    if profile_id is not None:
        profile_id = str(UUID(profile_id))
    with profile_db.profile_write_cursor() as cur:
        cur.execute(f"""SELECT * FROM participant_profiles WHERE NOT deleted AND merged_into IS NULL
            AND (%s::uuid IS NULL OR id = %s::uuid) AND {_DUE} AND assessment_attempts < %s
            AND assessment_next_attempt_at <= now() AND (assessment_claim_until IS NULL OR assessment_claim_until <= now())
            ORDER BY assessment_next_attempt_at, id FOR UPDATE SKIP LOCKED LIMIT 1""", (profile_id, profile_id, MAX_ATTEMPTS))
        found = cur.fetchone()
        if not found:
            return None
        row = dict(found)
        visible, claims = _snapshot(cur, row)
        signature = sections.input_hash(visible, claims)
        if signature == row.get("assessment_input_hash"):
            cur.execute("""UPDATE participant_profiles SET assessment_dirty = false, assessment_error = NULL,
                assessment_attempts = 0, assessment_claim_owner = NULL, assessment_claim_until = NULL WHERE id = %s""", (row["id"],))
            return {"skipped": True, "id": str(row["id"])}
        cur.execute("""UPDATE participant_profiles SET assessment_claim_owner = %s,
            assessment_claim_until = now() + (%s * interval '1 second') WHERE id = %s""", (owner, LEASE_SECONDS, row["id"]))
        return {"profile": visible, "claims": claims, "input_hash": signature, "id": str(row["id"])}


def apply(owner: str, snapshot: dict, candidates: dict, relationship_candidates: list[dict] | None = None) -> dict:
    from services.personas.assessment import validate_output, validate_relationships

    with profile_db.profile_write_cursor() as cur:
        row = profile_db._canonical(cur, snapshot["id"], lock=True)
        if not row or row["deleted"] or str(row["id"]) != snapshot["id"]:
            raise profile_db.ProfileRevisionConflict("Persona identity changed during assessment")
        cur.execute("SELECT assessment_claim_until > now() AS active FROM participant_profiles WHERE id = %s", (row["id"],))
        if row["assessment_claim_owner"] != owner or not cur.fetchone()["active"]:
            raise profile_db.ProfileRevisionConflict("Persona assessment lease expired")
        source_ids = ({claim["meeting_id"] for claim in row["claims"] if claim.get("meeting_id")}
                      | sections.source_ids([row])
                      | {proof["meeting_id"] for proof in row["metadata_provenance"].values() if proof.get("meeting_id")})
        cur.execute("SELECT analysis_evidence FROM profile_relationships WHERE subject_id=%s AND NOT dismissed", (row["id"],))
        source_ids.update(source["meeting_id"] for edge in cur.fetchall() for source in edge["analysis_evidence"].get("sources", []))
        if source_ids:
            # Freeze LIVE publication preconditions until narratives and their audit receipt commit together.
            cur.execute("""SELECT m.id FROM meeting_summaries m JOIN meeting_digestions d ON d.meeting_id = m.id
                WHERE m.id IN %s ORDER BY m.id FOR SHARE OF m, d""", (tuple(source_ids),))
        visible, claims = _snapshot(cur, row)
        signature = sections.input_hash(visible, claims)
        if signature != snapshot["input_hash"] or row["revision"] != snapshot["profile"]["revision"]:
            raise profile_db.ProfileRevisionConflict("Profile or evidence changed; assessment will retry from saved observations")
        candidates = validate_output(visible, claims, candidates)
        directed = validate_relationships(visible, claims, relationship_candidates if relationship_candidates is not None else relationship_insufficient(visible))
        known = {claim["id"]: claim for claim in claims}
        notes, proofs = deepcopy(row["section_notes"]), deepcopy(row["section_evidence"])
        contexts = profile_db._source_contexts(cur, [row], {claim["meeting_id"] for claim in claims})
        for key, item in candidates.items():
            ids = item["claim_ids"]
            chosen = [known[claim_id] for claim_id in ids]
            if item["text"]:
                notes[key] = item["text"]
            else:
                notes.pop(key, None)
            proofs[key] = {
                "human": False, "status": item["status"], "claim_ids": ids,
                "claim_signatures": {claim_id: known[claim_id]["signature"] for claim_id in ids},
                "sources": [{"meeting_id": meeting_id, "transcript_hash": contexts[meeting_id]["transcript_hash"],
                             "participants_revision": contexts[meeting_id]["participants_revision"]}
                            for meeting_id in sorted({claim["meeting_id"] for claim in chosen})],
                "coverage": sections.coverage(chosen), "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        edge_change = relationship_db.apply_assessments(cur, str(row["id"]), directed, claims, contexts)
        changed = bool(edge_change["after"]) or (notes, proofs) != (row["section_notes"], row["section_evidence"])
        cur.execute("""UPDATE participant_profiles SET section_notes = %s, section_evidence = %s,
            assessment_dirty = false, assessment_input_hash = %s, assessment_claim_owner = NULL, assessment_claim_until = NULL,
            assessment_attempts = 0, assessment_error = NULL, assessment_next_attempt_at = now(),
            revision = revision + %s, updated_at = CASE WHEN %s THEN clock_timestamp() ELSE updated_at END
            WHERE id = %s RETURNING *""", (Json(notes), Json(proofs), signature, int(changed), changed, row["id"]))
        updated = dict(cur.fetchone())
        if changed:
            revisions.record(cur, row, updated, actor="agent", source="assessment", input_hash=signature,
                             extra={"relationships": edge_change} if edge_change["after"] else None)
        return profile_db._detail(cur, updated)


def fail(profile_id: str, owner: str, error_type: str) -> None:
    with _cursor() as cur:
        cur.execute("""UPDATE participant_profiles SET assessment_attempts = assessment_attempts + 1,
            assessment_error = %s, assessment_claim_owner = NULL, assessment_claim_until = NULL,
            assessment_next_attempt_at = now() + (least(900, 30 * power(2, assessment_attempts)) * (0.8 + random() * 0.4) * interval '1 second')
            WHERE id = %s AND assessment_claim_owner = %s""", (error_type, profile_id, owner))


def release_owner(owner: str) -> None:
    with _cursor() as cur:
        cur.execute("UPDATE participant_profiles SET assessment_claim_owner = NULL, assessment_claim_until = NULL WHERE assessment_claim_owner = %s", (owner,))


def request(profile_id: str, expected_revision: int) -> dict:
    with profile_db.profile_write_cursor() as cur:
        row = profile_db._editable(cur, profile_id, expected_revision)
        cur.execute("""UPDATE participant_profiles SET assessment_dirty = true, assessment_attempts = 0,
            assessment_error = NULL, assessment_next_attempt_at = now() WHERE id = %s""", (row["id"],))
        return {"id": str(row["id"]), "revision": row["revision"]}


def insufficient(row: dict) -> dict:
    return {key: {"status": "insufficient_evidence", "text": "", "claim_ids": []}
            for key in profile_fields.SECTION_FIELDS - {"relationships"} if not sections.human(key, row)}


def relationship_insufficient(row: dict) -> list[dict]:
    from services.personas.assessment import editable_relationships

    return [{"target_id": edge["target_id"], "status": "insufficient_evidence", "text": "", "claim_ids": []}
            for edge in editable_relationships(row)]
