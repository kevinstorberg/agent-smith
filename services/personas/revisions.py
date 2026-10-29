from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from psycopg2.extras import Json

from services.meetings import profile_metadata
from services.meetings.db import _cursor, _serialize
from services.personas import sections

_FIELDS = ("display_name", "email", "identity_scope", "nicknames", "tags", "starred", "metadata",
           "metadata_provenance", "section_notes", "section_evidence", "deleted", "merged_into")


def record(cur, before: dict | None, after: dict, *, actor: str, source: str,
           source_id: str | None = None, input_hash: str | None = None, extra: dict | None = None) -> None:
    before = before or {}
    changes = {key: {"before": deepcopy(before.get(key)), "after": deepcopy(after.get(key))}
               for key in _FIELDS if before.get(key) != after.get(key)}
    old = {claim["id"]: claim for claim in before.get("claims", [])}
    new = {claim["id"]: claim for claim in after.get("claims", [])}
    claim_delta = {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
                   "changed": sorted(key for key in old.keys() & new.keys() if old[key] != new[key])}
    if any(claim_delta.values()):
        changes["claims"] = {"before": None, "after": claim_delta}
    changes.update(extra or {})
    if not changes:
        return
    # Proof travels with the changed text; history never relies on today's ownership flags.
    for key in ("metadata_provenance", "section_evidence"):
        if key.replace("_provenance", "") in changes or key == "section_evidence" and "section_notes" in changes:
            changes.setdefault(key, {"before": deepcopy(before.get(key, {})), "after": deepcopy(after.get(key, {}))})
    cur.execute("""INSERT INTO profile_revisions
        (profile_id, base_revision, new_revision, actor, source, source_id, input_hash, changes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (after["id"], before.get("revision", 0), after["revision"], actor, source, source_id, input_hash, Json(changes)))


def _project(cur, row: dict, current: dict) -> dict:
    from services.meetings import profile_db

    changes = deepcopy(row["changes"])
    snapshots = [{key: changes.get(key, {}).get(side) or {} for key in ("metadata", "metadata_provenance", "section_notes", "section_evidence")}
                 for side in ("before", "after")]
    contexts = profile_db._source_contexts(cur, [current, *snapshots],
                                          {claim["meeting_id"] for claim in current["claims"] if claim.get("meeting_id")})
    claims = sections.effective_claims(current, contexts)
    source_restricted = False
    for side, snapshot in zip(("before", "after"), snapshots):
        visible = sections.project(profile_metadata.project(snapshot, contexts), claims, contexts)
        source_restricted |= any(set(snapshot[key]) - set(visible[key]) for key in ("metadata", "section_notes"))
        for key in ("metadata", "metadata_provenance", "section_notes", "section_evidence"):
            if key in changes:
                changes[key][side] = visible[key]
    # Claim deltas are stable IDs only; withdrawn transcript text is never copied into history.
    return _serialize({**row, "changes": changes, "source_restricted": source_restricted})


def list_history(profile_id: str, *, limit: int = 10, offset: int = 0, revision_id: int | None = None) -> dict | None:
    from services.meetings import profile_db

    profile_id = str(UUID(profile_id))
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ValueError("History limit must be 1-100 and offset must be nonnegative")
    with _cursor() as cur:
        current = profile_db._canonical(cur, profile_id)
        if not current or current["deleted"]:
            return None
        key = current["id"]
        if revision_id is not None:
            cur.execute("""SELECT * FROM profile_revisions WHERE (profile_id = %s OR profile_id IN
                (SELECT id FROM participant_profiles WHERE merged_into = %s)) AND id = %s""", (key, key, revision_id))
            row = cur.fetchone()
            return _project(cur, dict(row), current) if row else None
        cur.execute("""SELECT count(*) AS total FROM profile_revisions WHERE profile_id = %s OR profile_id IN
            (SELECT id FROM participant_profiles WHERE merged_into = %s)""", (key, key))
        total = cur.fetchone()["total"]
        cur.execute("""SELECT * FROM profile_revisions WHERE profile_id = %s OR profile_id IN
            (SELECT id FROM participant_profiles WHERE merged_into = %s) ORDER BY id DESC LIMIT %s OFFSET %s""", (key, key, limit, offset))
        rows = [dict(row) for row in cur.fetchall()]
        return {"items": [_project(cur, row, current) for row in rows], "total": total}
