from __future__ import annotations

import json

from services.meetings import profile_db, profile_directory

PROFILE_CONTEXT_BYTES = 8_000


def _text(value, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _context(profile: dict) -> dict:
    metadata = profile.get("metadata") or {}
    relationships = profile.get("relationships") or []
    return {
        "profile_id": profile["id"], "name": profile["display_name"],
        "nicknames": [_text(name, 200) for name in profile.get("nicknames", [])[:6]],
        "emails": profile.get("emails", [])[:6],
        "company": _text(metadata.get("company"), 300), "job_role": _text(metadata.get("job_role"), 300),
        "overview": _text((profile.get("section_notes") or {}).get("overview"), 1500),
        "relationships": [{key: _text(edge.get(key), 200) for key in ("subject_name", "target_name", "label", "notes")} | {
            "human_confirmed": bool(edge.get("human_confirmed")),
            "analysis_human": bool((edge.get("analysis_evidence") or {}).get("human", edge.get("human_confirmed", False))), "dismissed": bool(edge.get("dismissed")),
        } for edge in relationships[:5]],
        "omitted": {"nicknames": max(0, len(profile.get("nicknames", [])) - 6),
                    "emails": max(0, len(profile.get("emails", [])) - 6),
                    "relationships": max(0, len(relationships) - 5)},
    }


def read_contexts(query: str, profile_id: str | None, known_ids: set[str]) -> dict:
    if profile_id is not None:
        if profile_id not in known_ids:
            return {"error": "Search known profiles by name, nickname, email, company or role before reading an unknown profile ID"}
        ids = [profile_id]
        total = 1
    elif query.strip():
        page = profile_db.list_profiles(query.strip(), limit=3, sort="name_asc")
        ids, total = [row["id"] for row in page["items"]], page["total"]
    else:
        page = profile_directory.names(limit=3)
        ids, total = [row["id"] for row in page["items"]], page["total"]
    envelope = {"items": [], "matched": total, "omitted": total}
    for profile_id in ids:
        profile = profile_db.get_profile(profile_id, include_evidence=False)
        if profile is None or profile.get("deleted"):
            continue
        item = _context(profile)
        candidate = {**envelope, "items": [*envelope["items"], item], "omitted": total - len(envelope["items"]) - 1}
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > PROFILE_CONTEXT_BYTES:
            break
        envelope["items"].append(item)
    envelope["omitted"] = total - len(envelope["items"])
    return envelope


def identity_candidates(contexts: list[dict]) -> list[dict]:
    return [{"name": name, "profile_id": profile["profile_id"], **({"email": email} if email else {})}
            for profile in contexts for name in [profile["name"], *profile.get("nicknames", [])]
            for email in (profile.get("emails") or [None])]
