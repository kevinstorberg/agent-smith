from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from psycopg2.extras import Json

from services.meetings import profile_db, relationship_analysis
from services.meetings.db import _serialize
from services.meetings.profile_fields import text


def for_profiles(cur, profiles: list[dict], *, include_dismissed: bool = False, include_overrides: bool = False,
                 include_evidence: bool = True, include_unavailable: bool = False,
                 include_card_state: bool = False) -> dict[str, list[dict]]:
    ids = tuple(str(row["id"]) for row in profiles)
    result = {key: [] for key in ids}
    if not ids:
        return result
    cur.execute("""SELECT r.*, subject.display_name AS subject_name, coalesce(target.display_name,r.target_name) AS target_name
        FROM profile_relationships r
        JOIN participant_profiles subject ON subject.id = r.subject_id
        LEFT JOIN participant_profiles target ON target.id = r.target_id
        WHERE (r.subject_id IN %s OR r.target_id IN %s)
          AND NOT subject.deleted AND (r.target_id IS NULL OR NOT target.deleted)
          AND subject.merged_into IS NULL AND (r.target_id IS NULL OR target.merged_into IS NULL)
          AND (%s OR NOT r.dismissed)
        ORDER BY lower(subject.display_name), lower(target.display_name), r.id""", (ids, ids, include_dismissed))
    edges = [dict(row) for row in cur.fetchall()]
    if not edges:
        return result
    source_ids = {str(row["subject_id"]) for row in edges}
    source_ids.update(row["analysis_evidence"]["legacy_profile_id"] for row in edges if row["analysis_evidence"].get("legacy_profile_id"))
    cur.execute("SELECT id, claims FROM participant_profiles WHERE id IN %s", (tuple(source_ids),))
    raw_subjects = {str(row["id"]): dict(row) for row in cur.fetchall()}
    subjects = {row["id"]: row for row in profile_db._visible(cur, list(raw_subjects.values()), include_overrides=include_overrides)}
    target_ids = {claim["target_id"] for row in raw_subjects.values() for claim in row["claims"] if claim.get("target_id")}
    canonical = profile_db.canonical_rows(cur, list(target_ids), metadata_only=True)
    contexts = profile_db._source_contexts(cur, list(raw_subjects.values()),
        {source["meeting_id"] for edge in edges for source in edge["analysis_evidence"].get("sources", [])}
        | {claim["meeting_id"] for row in raw_subjects.values() for claim in row["claims"] if claim.get("meeting_id")})
    for edge in edges:
        item = _serialize(edge)
        history = item.pop("history")
        item["history_count"] = len(history)
        if include_card_state:
            item["history"] = history
            item["raw_analysis_evidence"] = item["analysis_evidence"]
        claims = [claim for claim in subjects.get(item["subject_id"], {}).get("claims", [])
                  if claim.get("target_id") and canonical.get(claim["target_id"])
                  and str(canonical[claim["target_id"]]["id"]) == item["target_id"]]
        effective = []
        from services.personas import sections
        analysis_subject = item["analysis_evidence"].get("legacy_profile_id", item["subject_id"])
        for claim in sections.effective_claims(subjects.get(analysis_subject, {}), contexts):
            target = canonical.get(claim.get("target_id"))
            effective.append({**claim, "canonical_target_id": str(target["id"]) if target else claim.get("target_id")})
        item = relationship_analysis.project(item, effective, contexts, full_proof=include_overrides)
        if include_card_state:
            proof = item["raw_analysis_evidence"]
            relevant = [claim for claim in raw_subjects.get(analysis_subject, {}).get("claims", [])
                        if claim["id"] in proof.get("claim_ids", []) or claim.get("target_id")
                        and canonical.get(claim["target_id"]) and str(canonical[claim["target_id"]]["id"]) == item["target_id"]]
            source_ids = {claim["meeting_id"] for claim in relevant} | {source["meeting_id"] for source in proof.get("sources", [])}
            item["source_version"] = sections.digest({"sources": {key: contexts.get(key) for key in sorted(source_ids)},
                                                      "claims": {claim["id"]: sections.claim_signature(claim) for claim in relevant}})
        item["claim_count"] = len(claims)
        if not claims and not item["human_confirmed"] and not item["dismissed"] and not include_unavailable:
            continue
        if include_overrides:
            item["claims_available_via"] = {"tool": "get_profile", "profile_id": item["subject_id"]}
        else:
            item["claims"] = claims if include_evidence else []
        for key in (item["subject_id"], item["target_id"]):
            if key in result:
                result[key].append(item)
    return result


def _detail(cur, relationship_id: str, *, include_evidence: bool = True) -> dict:
    cur.execute("SELECT subject_id FROM profile_relationships WHERE id = %s", (relationship_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError("Relationship no longer exists; refresh the profile")
    items = for_profiles(cur, [{"id": row["subject_id"]}], include_dismissed=True, include_evidence=include_evidence)
    found = next((item for group in items.values() for item in group if item["id"] == relationship_id), None)
    if found is None:
        raise ValueError("Relationship is unavailable because a profile changed")
    return found


def create(profile_id: str, target_id: str, expected_revision: int, target_revision: int, label: str = "", notes: str | None = None,
           *, include_evidence: bool = True) -> dict:
    proof = {"version": 1, "human": notes is not None}
    label, notes = text(label, "Relationship label", 200), text(notes or "", "Relationship notes")
    with profile_db.profile_write_cursor() as cur:
        subject = profile_db._editable(cur, profile_id, expected_revision)
        target = profile_db._editable(cur, target_id, target_revision)
        if subject["id"] == target["id"]:
            raise ValueError("A relationship must connect two different people")
        cur.execute("""INSERT INTO profile_relationships (subject_id, target_id, label, notes, human_confirmed, analysis_evidence)
            VALUES (%s, %s, %s, %s, true, %s)
            ON CONFLICT (subject_id, target_id) DO UPDATE SET label = EXCLUDED.label,
              notes = EXCLUDED.notes, analysis_evidence=EXCLUDED.analysis_evidence, dismissed = false, human_confirmed = true, revision = profile_relationships.revision + 1,
              updated_at = clock_timestamp() WHERE profile_relationships.dismissed
            RETURNING *""", (subject["id"], target["id"], label, notes, Json(proof)))
        row = cur.fetchone()
        if row is None:
            raise profile_db.ProfileRevisionConflict("These people already have a relationship; edit that relationship instead")
        _touch_profiles(cur, (subject["id"], target["id"]), None, dict(row))
        return _detail(cur, str(row["id"]), include_evidence=include_evidence)


def _editable(cur, profile_id: str, relationship_id: str, expected_revision: int) -> dict:
    profile_db._expected_revision(expected_revision)
    profile = profile_db._canonical(cur, profile_id, lock=True)
    if profile is None or profile["deleted"]:
        raise ValueError("Profile does not exist")
    cur.execute("SELECT * FROM profile_relationships WHERE id = %s FOR UPDATE", (str(UUID(relationship_id)),))
    edge = cur.fetchone()
    if edge is None or profile["id"] not in (edge["subject_id"], edge["target_id"]) or edge["dismissed"]:
        raise ValueError("Relationship does not exist on this profile")
    if edge["revision"] != expected_revision:
        raise profile_db.ProfileRevisionConflict("Relationship changed; refresh before saving")
    cur.execute("SELECT id FROM participant_profiles WHERE id IN %s AND (deleted OR merged_into IS NOT NULL)",
                ((edge["subject_id"], edge["target_id"]),))
    if cur.fetchone():
        raise profile_db.ProfileRevisionConflict("A linked profile changed; refresh before saving")
    return dict(edge)


def _touch_profiles(cur, ids, previous: dict | None, current: dict) -> None:
    from services.personas import revisions

    ids = tuple(dict.fromkeys(value for value in ids if value is not None))
    cur.execute("SELECT * FROM participant_profiles WHERE id IN %s ORDER BY id FOR UPDATE", (ids,))
    before = {row["id"]: dict(row) for row in cur.fetchall()}
    cur.execute("""UPDATE participant_profiles SET revision = revision + 1, assessment_dirty = true,
        assessment_attempts = 0, assessment_error = NULL, assessment_next_attempt_at = now(),
        updated_at = clock_timestamp() WHERE id IN %s RETURNING *""", (tuple(ids),))
    after = [dict(row) for row in cur.fetchall()]
    change = {side: [history_snapshot(cur, edge)] if edge is not None else []
              for side, edge in (("before", previous), ("after", current))}
    for row in after:
        revisions.record(cur, before[row["id"]], row, actor="human", source="manual",
                         extra={"relationships": change})


def update(profile_id: str, relationship_id: str, expected_revision: int, *, label: str | None = None,
           notes: str | None = None, allow_agent_notes: bool = False, include_evidence: bool = True) -> dict:
    if type(allow_agent_notes) is not bool or allow_agent_notes and notes is not None:
        raise ValueError("Automatic relationship updates cannot be released together with a notes edit")
    if label is None and notes is None and not allow_agent_notes:
        raise ValueError("Provide a relationship label or notes")
    with profile_db.profile_write_cursor() as cur:
        edge = _editable(cur, profile_id, relationship_id, expected_revision)
        new_label = text(label, "Relationship label", 200) if label is not None else edge["label"]
        new_notes = text(notes, "Relationship notes") if notes is not None else edge["notes"]
        proof = {"version": 1, "human": True} if notes is not None else dict(edge["analysis_evidence"])
        if allow_agent_notes:
            proof = {**proof, "human": False}
            if "claim_ids" not in proof:
                proof = {"version": 1, "human": False, "origin": "human"}
        edit_in_transaction(cur, edge, label=new_label, notes=new_notes, proof=proof)
        return _detail(cur, str(edge["id"]), include_evidence=include_evidence)


def edit_in_transaction(cur, edge: dict, *, label: str, notes: str, proof: dict,
                        receipts: list[dict] | None = None, target_id=Ellipsis, target_name: str | None = None,
                        dismissed: bool | None = None) -> dict:
    target_id = edge["target_id"] if target_id is Ellipsis else target_id
    target_name = edge.get("target_name", "") if target_name is None else target_name
    dismissed = edge["dismissed"] if dismissed is None else dismissed
    changed = (label, notes, proof, str(target_id), target_name, dismissed) != (
        edge["label"], edge["notes"], edge["analysis_evidence"], str(edge["target_id"]), edge.get("target_name", ""), edge["dismissed"])
    if not changed and not receipts and edge["human_confirmed"]:
        return edge
    history = edge["history"] + [{"action": "edit", **history_snapshot(cur, edge),
                                  "timestamp": datetime.now(timezone.utc).isoformat()}, *(receipts or [])]
    _validate_history(history)
    cur.execute("""UPDATE profile_relationships SET label=%s,notes=%s,analysis_evidence=%s,history=%s,
        target_id=%s,target_name=%s,dismissed=%s,human_confirmed=true,revision=revision+1,
        updated_at=clock_timestamp() WHERE id=%s RETURNING *""",
                (label, notes, Json(proof), Json(history), target_id, target_name, dismissed, edge["id"]))
    updated = dict(cur.fetchone())
    _touch_profiles(cur, (edge["subject_id"], edge["target_id"], target_id), edge, updated)
    return updated


def delete(profile_id: str, relationship_id: str, expected_revision: int) -> None:
    with profile_db.profile_write_cursor() as cur:
        edge = _editable(cur, profile_id, relationship_id, expected_revision)
        cur.execute("UPDATE profile_relationships SET dismissed = true, revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s RETURNING *", (edge["id"],))
        updated = dict(cur.fetchone())
        _touch_profiles(cur, (edge["subject_id"], edge["target_id"]), edge, updated)


def ensure_claim_links(cur, claims: list[dict]) -> None:
    pairs = sorted({(str(claim["subject_id"]), str(claim["target_id"])) for claim in claims if claim.get("target_id")})
    for subject, target in pairs:
        if subject != target:
            cur.execute("""INSERT INTO profile_relationships (subject_id, target_id) VALUES (%s, %s)
                ON CONFLICT (subject_id, target_id) DO NOTHING""", (subject, target))


def _validate_history(history: list[dict]) -> None:
    if len(json.dumps(history).encode()) > 2_000_000:
        raise ValueError("Relationship history exceeds the storage limit")


def history_snapshot(cur, edge: dict) -> dict:
    fields = ("id", "subject_id", "target_id", "label", "notes", "dismissed", "human_confirmed", "analysis_evidence")
    result = _serialize({key: edge[key] for key in fields})
    cur.execute("SELECT id,display_name FROM participant_profiles WHERE id IN %s", ((edge["subject_id"], edge["target_id"]),))
    names = {str(row["id"]): row["display_name"] for row in cur.fetchall()}
    return {**result, "subject_name": names.get(str(edge["subject_id"]), "Unavailable profile"),
            "target_name": names.get(str(edge["target_id"]), edge.get("target_name") or "Unavailable profile")}


def apply_assessments(cur, profile_id: str, candidates: list[dict], claims: list[dict], contexts: dict) -> dict:
    cur.execute("SELECT * FROM profile_relationships WHERE subject_id=%s AND NOT dismissed ORDER BY id FOR UPDATE", (profile_id,))
    edges = {str(row["target_id"]): dict(row) for row in cur.fetchall()}
    before, after = [], []
    for item in candidates:
        edge = edges.get(item["target_id"])
        if edge is None or relationship_analysis.human(edge):
            raise profile_db.ProfileRevisionConflict("Relationship ownership or identity changed during assessment")
        proof = relationship_analysis.proof(edge, item, claims, contexts)
        previous = history_snapshot(cur, edge)
        history = edge["history"] + [{"action": "assessment", **previous}]
        _validate_history(history)
        cur.execute("""UPDATE profile_relationships SET notes=%s,analysis_evidence=%s,history=%s,
            revision=revision+1,updated_at=clock_timestamp() WHERE id=%s RETURNING *""",
                    (item["text"], Json(proof), Json(history), edge["id"]))
        before.append(previous)
        after.append(history_snapshot(cur, dict(cur.fetchone())))
    return {"before": before, "after": after}


def rebase_analysis(cur, profile_id: str, previous_claims: list[dict], claims: list[dict], before: dict, after: dict) -> bool:
    from services.personas import sections

    cur.execute("SELECT * FROM profile_relationships WHERE subject_id=%s AND NOT dismissed ORDER BY id FOR UPDATE", (profile_id,))
    stale = False
    current = {claim["id"]: claim for claim in claims}
    for found in cur.fetchall():
        edge = dict(found)
        proof = edge["analysis_evidence"]
        if relationship_analysis.human(edge):
            continue
        if sections.proof_valid(proof, previous_claims, before) and all(key in current for key in proof.get("claim_ids", [])):
            updated = {**proof, "claim_signatures": {key: current[key]["signature"] for key in proof["claim_ids"]},
                       "sources": [{"meeting_id": source["meeting_id"], "transcript_hash": after[source["meeting_id"]]["transcript_hash"],
                                    "participants_revision": after[source["meeting_id"]]["participants_revision"]}
                                   for source in proof.get("sources", [])]}
            cur.execute("UPDATE profile_relationships SET analysis_evidence=%s WHERE id=%s", (Json(updated), edge["id"]))
        elif proof.get("status") == "supported":
            stale = True
    return stale


def merge_profile_links(cur, source_id: str, target_id: str) -> None:
    cur.execute("SELECT * FROM profile_relationships WHERE subject_id = %s OR target_id = %s ORDER BY id FOR UPDATE", (source_id, source_id))
    edges = [dict(row) for row in cur.fetchall()]
    if edges:
        cur.execute("""UPDATE participant_profiles SET assessment_dirty=true,assessment_attempts=0,assessment_error=NULL,
            assessment_next_attempt_at=clock_timestamp() WHERE id IN %s AND NOT deleted""",
                    (tuple({str(edge["subject_id"]) for edge in edges} | {target_id}),))
    for edge in edges:
        subject = target_id if str(edge["subject_id"]) == source_id else str(edge["subject_id"])
        target = target_id if str(edge["target_id"]) == source_id else str(edge["target_id"]) if edge["target_id"] else None
        if subject == target:
            # Keep the original identity pair as hidden history rather than making a self-link.
            cur.execute("UPDATE profile_relationships SET dismissed = true, revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s", (edge["id"],))
            continue
        cur.execute("""SELECT * FROM profile_relationships WHERE subject_id = %s AND target_id IS NOT DISTINCT FROM %s
            AND (%s IS NOT NULL OR lower(target_name)=lower(%s)) AND id <> %s FOR UPDATE""", (subject, target, target, edge["target_name"], edge["id"]))
        winner = cur.fetchone()
        if winner is None:
            history = edge["history"] + [{"action": "merge", **history_snapshot(cur, edge)}]
            _validate_history(history)
            proof = {"version": 1, "human": relationship_analysis.human(edge)}
            if edge["analysis_evidence"].get("origin") == "human":
                proof["origin"] = "human"
            cur.execute("""UPDATE profile_relationships SET subject_id=%s,target_id=%s,notes=%s,analysis_evidence=%s,
                history=%s,revision=revision+1,updated_at=clock_timestamp() WHERE id=%s""",
                        (subject, target, edge["notes"] if proof["human"] or proof.get("origin") == "human" else "", Json(proof), Json(history), edge["id"]))
            continue
        winner = dict(winner)
        chosen = winner if relationship_analysis.human(winner) else edge if relationship_analysis.human(edge) else (
            winner if winner["analysis_evidence"].get("origin") == "human" else edge if edge["analysis_evidence"].get("origin") == "human" else None)
        notes = chosen["notes"] if chosen else ""
        proof = {"version": 1, "human": relationship_analysis.human(chosen), "origin": "human"} if chosen else {"version": 1, "human": False}
        history = winner["history"] + edge["history"] + [{"action": "merge", "before": [history_snapshot(cur, winner), history_snapshot(cur, edge)]}]
        _validate_history(history)
        cur.execute("""UPDATE profile_relationships SET label = %s, notes = %s, dismissed = %s, history = %s, analysis_evidence=%s,
            human_confirmed = %s,
            revision = greatest(revision, %s) + 1, updated_at = clock_timestamp() WHERE id = %s""",
                    (winner["label"] or edge["label"], notes, winner["dismissed"] or edge["dismissed"], Json(history), Json(proof),
                     winner["human_confirmed"] or edge["human_confirmed"], edge["revision"], winner["id"]))
        cur.execute("DELETE FROM profile_relationships WHERE id = %s", (edge["id"],))


def project_history(cur, edge: dict) -> dict:
    from services.personas import sections

    if not edge.get("analysis_evidence"):
        return edge
    row = profile_db._canonical(cur, edge["analysis_evidence"].get("legacy_profile_id", edge["subject_id"]))
    rows = [row] if row and not row["deleted"] else []
    contexts = profile_db._source_contexts(cur, rows,
        {source["meeting_id"] for source in edge["analysis_evidence"].get("sources", [])}
        | {claim["meeting_id"] for profile in rows for claim in profile["claims"]})
    claims = sections.effective_claims(row, contexts) if rows else []
    targets = profile_db.canonical_rows(cur, [claim["target_id"] for claim in claims if claim.get("target_id")], metadata_only=True)
    claims = [{**claim, "canonical_target_id": str(targets[claim["target_id"]]["id"]) if targets.get(claim.get("target_id")) else claim.get("target_id")} for claim in claims]
    return relationship_analysis.project(edge, claims, contexts)
