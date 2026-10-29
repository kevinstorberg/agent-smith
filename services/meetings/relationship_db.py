from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from psycopg2.extras import Json

from services.meetings import profile_db
from services.meetings.db import _serialize
from services.meetings.profile_fields import text


def for_profiles(cur, profiles: list[dict], *, include_dismissed: bool = False, include_overrides: bool = False) -> dict[str, list[dict]]:
    ids = tuple(str(row["id"]) for row in profiles)
    result = {key: [] for key in ids}
    if not ids:
        return result
    cur.execute("""SELECT r.*, subject.display_name AS subject_name, target.display_name AS target_name
        FROM profile_relationships r
        JOIN participant_profiles subject ON subject.id = r.subject_id
        JOIN participant_profiles target ON target.id = r.target_id
        WHERE (r.subject_id IN %s OR r.target_id IN %s)
          AND NOT subject.deleted AND NOT target.deleted
          AND subject.merged_into IS NULL AND target.merged_into IS NULL
          AND (%s OR NOT r.dismissed)
        ORDER BY lower(subject.display_name), lower(target.display_name), r.id""", (ids, ids, include_dismissed))
    edges = [dict(row) for row in cur.fetchall()]
    if not edges:
        return result
    cur.execute("SELECT * FROM participant_profiles WHERE id IN %s", (tuple({row["subject_id"] for row in edges}),))
    subjects = {row["id"]: row for row in profile_db._visible(cur, [dict(row) for row in cur.fetchall()], include_overrides=include_overrides)}
    target_ids = {claim["target_id"] for row in subjects.values() for claim in row["claims"] if claim.get("target_id")}
    canonical = profile_db.canonical_rows(cur, list(target_ids), metadata_only=True)
    for edge in edges:
        item = _serialize(edge)
        item["history_count"] = len(item.pop("history"))
        claims = [claim for claim in subjects.get(item["subject_id"], {}).get("claims", [])
                  if claim.get("target_id") and canonical.get(claim["target_id"])
                  and str(canonical[claim["target_id"]]["id"]) == item["target_id"]]
        item["claim_count"] = len(claims)
        if not claims and not item["human_confirmed"] and not item["dismissed"]:
            continue
        if include_overrides:
            item["claims_available_via"] = {"tool": "get_profile", "profile_id": item["subject_id"]}
        else:
            item["claims"] = claims
        for key in (item["subject_id"], item["target_id"]):
            if key in result:
                result[key].append(item)
    return result


def _detail(cur, relationship_id: str) -> dict:
    cur.execute("SELECT subject_id FROM profile_relationships WHERE id = %s", (relationship_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError("Relationship no longer exists; refresh the profile")
    items = for_profiles(cur, [{"id": row["subject_id"]}], include_dismissed=True)
    found = next((item for group in items.values() for item in group if item["id"] == relationship_id), None)
    if found is None:
        raise ValueError("Relationship is unavailable because a profile changed")
    return found


def create(profile_id: str, target_id: str, expected_revision: int, target_revision: int, label: str = "", notes: str = "") -> dict:
    label, notes = text(label, "Relationship label", 200), text(notes, "Relationship notes")
    with profile_db.profile_write_cursor() as cur:
        subject = profile_db._editable(cur, profile_id, expected_revision)
        target = profile_db._editable(cur, target_id, target_revision)
        if subject["id"] == target["id"]:
            raise ValueError("A relationship must connect two different people")
        cur.execute("""INSERT INTO profile_relationships (subject_id, target_id, label, notes, human_confirmed)
            VALUES (%s, %s, %s, %s, true)
            ON CONFLICT (subject_id, target_id) DO UPDATE SET label = EXCLUDED.label,
              notes = EXCLUDED.notes, dismissed = false, human_confirmed = true, revision = profile_relationships.revision + 1,
              updated_at = clock_timestamp() WHERE profile_relationships.dismissed
            RETURNING *""", (subject["id"], target["id"], label, notes))
        row = cur.fetchone()
        if row is None:
            raise profile_db.ProfileRevisionConflict("These people already have a relationship; edit that relationship instead")
        _touch_profiles(cur, (subject["id"], target["id"]), None, dict(row))
        return _detail(cur, str(row["id"]))


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

    cur.execute("SELECT * FROM participant_profiles WHERE id IN %s ORDER BY id FOR UPDATE", (tuple(ids),))
    before = {row["id"]: dict(row) for row in cur.fetchall()}
    cur.execute("""UPDATE participant_profiles SET revision = revision + 1, assessment_dirty = true,
        assessment_attempts = 0, assessment_error = NULL, assessment_next_attempt_at = now(),
        updated_at = clock_timestamp() WHERE id IN %s RETURNING *""", (tuple(ids),))
    after = [dict(row) for row in cur.fetchall()]
    fields = ("id", "subject_id", "target_id", "label", "notes", "dismissed", "human_confirmed")
    change = {side: _serialize({key: edge[key] for key in fields}) if edge is not None else None
              for side, edge in (("before", previous), ("after", current))}
    for row in after:
        revisions.record(cur, before[row["id"]], row, actor="human", source="manual",
                         extra={"relationships": change})


def update(profile_id: str, relationship_id: str, expected_revision: int, *, label: str | None = None, notes: str | None = None) -> dict:
    if label is None and notes is None:
        raise ValueError("Provide a relationship label or notes")
    with profile_db.profile_write_cursor() as cur:
        edge = _editable(cur, profile_id, relationship_id, expected_revision)
        new_label = text(label, "Relationship label", 200) if label is not None else edge["label"]
        new_notes = text(notes, "Relationship notes") if notes is not None else edge["notes"]
        if (new_label, new_notes) != (edge["label"], edge["notes"]) or not edge["human_confirmed"]:
            history = edge["history"] + [{"action": "edit", "label": edge["label"], "notes": edge["notes"],
                                           "timestamp": datetime.now(timezone.utc).isoformat()}]
            _validate_history(history)
            cur.execute("""UPDATE profile_relationships SET label = %s, notes = %s, history = %s, human_confirmed = true,
                revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s RETURNING *""",
                        (new_label, new_notes, Json(history), edge["id"]))
            updated = dict(cur.fetchone())
            _touch_profiles(cur, (edge["subject_id"], edge["target_id"]), edge, updated)
        return _detail(cur, str(edge["id"]))


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


def merge_profile_links(cur, source_id: str, target_id: str) -> None:
    cur.execute("SELECT * FROM profile_relationships WHERE subject_id = %s OR target_id = %s ORDER BY id FOR UPDATE", (source_id, source_id))
    edges = [dict(row) for row in cur.fetchall()]
    for edge in edges:
        subject = target_id if str(edge["subject_id"]) == source_id else str(edge["subject_id"])
        target = target_id if str(edge["target_id"]) == source_id else str(edge["target_id"])
        if subject == target:
            # Keep the original identity pair as hidden history rather than making a self-link.
            cur.execute("UPDATE profile_relationships SET dismissed = true, revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s", (edge["id"],))
            continue
        cur.execute("SELECT * FROM profile_relationships WHERE subject_id = %s AND target_id = %s AND id <> %s FOR UPDATE", (subject, target, edge["id"]))
        winner = cur.fetchone()
        if winner is None:
            cur.execute("UPDATE profile_relationships SET subject_id = %s, target_id = %s, revision = revision + 1, updated_at = clock_timestamp() WHERE id = %s", (subject, target, edge["id"]))
            continue
        winner = dict(winner)
        note_parts = [winner["notes"], edge["notes"]]
        if winner["label"] and edge["label"] and winner["label"] != edge["label"]:
            note_parts.append("Also described as: " + edge["label"])
        notes = "\n\n".join(dict.fromkeys(part for part in note_parts if part))
        text(notes, "Combined relationship notes")
        history = winner["history"] + edge["history"] + [{"action": "merge", "relationship": _serialize(edge)}]
        _validate_history(history)
        cur.execute("""UPDATE profile_relationships SET label = %s, notes = %s, dismissed = %s, history = %s,
            human_confirmed = %s,
            revision = greatest(revision, %s) + 1, updated_at = clock_timestamp() WHERE id = %s""",
                    (winner["label"] or edge["label"], notes, winner["dismissed"] or edge["dismissed"], Json(history),
                     winner["human_confirmed"] or edge["human_confirmed"], edge["revision"], winner["id"]))
        cur.execute("DELETE FROM profile_relationships WHERE id = %s", (edge["id"],))
