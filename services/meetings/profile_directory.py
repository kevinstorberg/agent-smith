from __future__ import annotations

import json
from uuid import UUID

from services.meetings import profile_db, profile_metadata
from services.meetings.db import _cursor

DIRECTORY_CHARS = 8_000
IDENTITY_FIELDS = ("id", "identity_key", "display_name", "email", "identity_scope")


def names(query: str = "", *, offset: int = 0, limit: int = 20) -> dict:
    if not isinstance(query, str) or len(query) > 1000:
        raise ValueError("Profile directory query must contain at most 1000 characters")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Profile directory offset must be nonnegative and limit must be 1-100")
    where = "NOT p.deleted AND p.merged_into IS NULL"
    params = []
    if query.strip():
        where += """ AND (p.display_name ILIKE %s OR p.email ILIKE %s
            OR EXISTS (SELECT 1 FROM unnest(p.nicknames) name WHERE name ILIKE %s)
            OR EXISTS (SELECT 1 FROM participant_profiles alias WHERE alias.merged_into=p.id
                AND (alias.display_name ILIKE %s OR alias.email ILIKE %s)))"""
        params = [f"%{query.strip()}%"] * 5
    with _cursor() as cur:
        cur.execute(f"SELECT count(*) AS total FROM participant_profiles p WHERE {where}", params)
        total = cur.fetchone()["total"]
        cur.execute(f"""SELECT p.id::text,p.display_name,p.nicknames,p.revision,
            ARRAY(SELECT DISTINCT alias.display_name FROM participant_profiles alias
                WHERE alias.merged_into=p.id ORDER BY alias.display_name) AS aliases,
            jsonb_strip_nulls(jsonb_build_object('company',left(visible.metadata->>'company',300),
                'job_role',left(visible.metadata->>'job_role',300),'supervisor',left(visible.metadata->>'supervisor',300))) AS metadata,
            (SELECT coalesce(jsonb_object_agg(field.key,jsonb_build_object('human',true)), '{{}}'::jsonb)
                FROM jsonb_each(p.metadata_provenance) field WHERE field.value->>'human'='true') AS metadata_provenance,
            ARRAY(SELECT DISTINCT lower(email) FROM participant_profiles identity
                WHERE (identity.id=p.id OR identity.merged_into=p.id) AND identity.email IS NOT NULL
                ORDER BY lower(email)) AS emails
            FROM participant_profiles p CROSS JOIN LATERAL (SELECT {profile_metadata.visible_sql('p')} AS metadata) visible WHERE {where}
            ORDER BY lower(p.display_name),p.id LIMIT %s OFFSET %s""", [*params, limit, offset])
        rows = [dict(row) for row in cur.fetchall()]
    items = []
    for row in rows:
        candidate = {"items": [*items, row], "total": total, "next_offset": offset + len(items) + 1}
        if len(json.dumps(candidate, ensure_ascii=False)) > DIRECTORY_CHARS:
            if not items:
                raise ValueError("One profile directory entry exceeds the read budget; reduce its aliases or nicknames")
            break
        items.append(row)
    next_offset = offset + len(items)
    return {"items": items, "total": total, "next_offset": next_offset if next_offset < total else None,
            "complete": next_offset >= total}


def snapshot() -> dict:
    page = names(limit=100)
    items = [{"id": row["id"], "display_name": row["display_name"]} for row in page["items"]]
    return {**page, "items": items, "lookup_tool": "list_profile_names"}


def participant(profile: dict) -> dict:
    return {key: profile[key] for key in IDENTITY_FIELDS} | {"segment_ids": []}


def extend_catalog(participants: list[dict], artifact: dict) -> list[dict]:
    catalog = {row["id"]: row for row in participants}
    for row in artifact.get("directory_participants", []):
        existing = catalog.get(row["id"])
        if row.get("segment_ids") != [] or existing and existing.get("segment_ids"):
            raise ValueError("Directory identities cannot replace mapped meeting speakers")
        if existing:
            if existing.get("identity_key") != row.get("identity_key"):
                raise profile_db.ProfileRevisionConflict("Directory profile identity changed")
            continue
        catalog[row["id"]] = row
    return list(profile_db._catalog(list(catalog.values())).values())


def checkpoint_targets(artifact: dict, participants: list[dict], result: dict) -> list[dict]:
    catalog = {row["id"]: row for row in participants}
    for row in result.get("directory_participants", []):
        profile_id = str(UUID(row["id"]))
        revision = row.get("revision")
        if profile_id in catalog or type(revision) is not int or revision < 1 or row.get("segment_ids") != []:
            raise ValueError("Directory target must be a new canonical profile with its current revision")
        identity = participant(row)
        artifact.setdefault("directory_participants", []).append(identity)
        artifact["expected_revisions"][profile_id] = revision
        catalog[profile_id] = identity
    return list(profile_db._catalog(list(catalog.values())).values())
