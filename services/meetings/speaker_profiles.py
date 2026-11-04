from __future__ import annotations

import json

from services.meetings import profile_db, profile_directory
from services.meetings.speaker_context import SpeakerContextTooLarge, candidates, encoded_size, identities

PROFILE_CONTEXT_BYTES = 8_000


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _context(profile: dict) -> dict:
    metadata = profile.get("metadata") or {}
    relationships = profile.get("relationships") or []
    return {
        "profile_id": profile["id"], "name": profile["display_name"],
        "revision": profile.get("revision", 0),
        "nicknames": [_text(name) for name in profile.get("nicknames", [])],
        "aliases": [_text(alias["display_name"]) for alias in profile.get("aliases", [])],
        "emails": profile.get("emails", []),
        "company": _text(metadata.get("company")), "job_role": _text(metadata.get("job_role")),
        "metadata": {field: _text(value) for field, value in metadata.items()},
        "metadata_provenance": {field: {"human": bool(proof.get("human"))} for field, proof in profile.get("metadata_provenance", {}).items()},
        "overview": _text((profile.get("section_notes") or {}).get("overview")),
        "relationships": [{key: _text(edge.get(key)) for key in ("subject_name", "target_name", "label", "notes")} | {
            "human_confirmed": bool(edge.get("human_confirmed")),
            "analysis_human": bool((edge.get("analysis_evidence") or {}).get("human", edge.get("human_confirmed", False))), "dismissed": bool(edge.get("dismissed")),
        } for edge in relationships],

    }


def read_contexts(query: str, profile_id: str | None, known_ids: set[str], *, offset: int = 0, limit: int = 10) -> dict:
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Profile context offset must be nonnegative and limit must be 1-100")
    if profile_id is not None:
        if profile_id not in known_ids:
            return {"error": "Search known profiles by name, nickname, email, company or role before reading an unknown profile ID"}
        ids, total = ([profile_id] if offset == 0 else []), 1
    elif query.strip():
        page = profile_db.list_profiles(query.strip(), offset=offset, limit=limit, sort="name_asc")
        ids, total = [row["id"] for row in page["items"]], page["total"]
    else:
        page = profile_directory.names(offset=offset, limit=limit)
        ids, total = [row["id"] for row in page["items"]], page["total"]
    envelope = {"items": [], "matched": total, "next_offset": None, "complete": True}
    consumed = 0
    for key in ids:
        profile = profile_db.get_profile(key, include_evidence=False)
        if profile is None or profile.get("deleted"):
            consumed += 1
            continue
        item = _context(profile)
        candidate = {**envelope, "items": [*envelope["items"], item], "next_offset": offset + consumed + 1, "complete": False}
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > PROFILE_CONTEXT_BYTES:
            if not envelope["items"]:
                raise SpeakerContextTooLarge("One complete known profile exceeds the context read budget")
            break
        envelope["items"].append(item)
        consumed += 1
    next_offset = offset + consumed
    if next_offset < total and consumed == 0:
        raise ValueError("Known profile context pagination did not advance")
    envelope.update(next_offset=next_offset if next_offset < total else None, complete=next_offset >= total)
    return envelope


def identity_candidates(contexts: list[dict]) -> list[dict]:
    return identities(contexts)


def directory_candidates(rows: list[dict]) -> list[dict]:
    return identity_candidates([{**row, "name": row["display_name"], "profile_id": row["id"]} for row in rows])


def attached_candidates(snapshot: dict) -> list[dict]:
    selected, seen = [], set()
    for person in candidates(snapshot):
        key = person.get("profile_id") or person.get("email")
        if not key or key in seen:
            continue
        seen.add(key)
        offset = 0
        while offset is not None:
            envelope = read_contexts("" if person.get("profile_id") else person["email"], person.get("profile_id"), {key}, offset=offset)
            for context in envelope.get("items", []):
                context = {**context, "metadata": {field: value for field, value in context["metadata"].items()
                                                   if field in {"company", "job_role", "supervisor"}}}
                for candidate in identity_candidates([context]):
                    if candidate not in selected:
                        if encoded_size([*selected, candidate]) > PROFILE_CONTEXT_BYTES:
                            raise SpeakerContextTooLarge("Complete attached speaker identities exceed the context budget")
                        selected.append(candidate)
            next_offset = envelope.get("next_offset")
            if next_offset is not None and next_offset <= offset:
                raise ValueError("Attached profile context pagination did not advance")
            offset = next_offset
    return selected
