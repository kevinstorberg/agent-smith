from __future__ import annotations

from services.meetings import profile_db
from services.meetings.participants import email_participant


def people(cur, provider: list, assignments: list[dict]) -> dict:
    entries, identities = [], []
    for source, values in (("provider", provider), ("manual", assignments)):
        for value in values:
            value = value if isinstance(value, dict) else {"name": str(value)}
            identity = None
            if source == "manual" and value.get("profile_id"):
                identity = {"id": value["profile_id"], "identity_key": "profile:" + value["profile_id"],
                            "display_name": value.get("name", ""), "email": value.get("email"), "identity_scope": "manual", "segment_ids": []}
            elif value.get("email"):
                try:
                    identity = email_participant(value["email"], value.get("name") or "")
                except ValueError:
                    pass
            if identity:
                identities.append(identity)
            reference = "statement:" + value["segment_id"] if value.get("segment_id") else "channel:" + value["speaker_key"] if value.get("speaker_key") else None
            entries.append((source, value, identity, reference))
    known = profile_db.canonical_rows(cur, [entry["id"] for entry in identities], metadata_only=True)
    groups, unlinked = {}, []
    for source, value, identity, reference in entries:
        canonical = known.get(identity["id"]) if identity else None
        linked = canonical if canonical and not canonical["deleted"] else None
        key = "profile:" + str(linked["id"]) if linked else identity["identity_key"] if identity and identity["identity_scope"] == "email" else reference
        if key is None:
            unlinked.append({"source": source, "participant": value})
            continue
        group = groups.setdefault(key, {"key": key, "profile_id": str(linked["id"]) if linked else None,
            "display_name": linked["display_name"] if linked else value.get("name") or value.get("email") or "Unnamed participant",
            "emails": [], "names": [], "sources": [], "assignments": []})
        if isinstance(value.get("name"), str) and value["name"] not in group["names"]:
            group["names"].append(value["name"])
        if isinstance(value.get("email"), str):
            email = value["email"].strip().casefold()
            if email not in group["emails"]:
                group["emails"].append(email)
        if source not in group["sources"]:
            group["sources"].append(source)
        if source == "manual":
            group["assignments"].append(value)
    return {"people": sorted(groups.values(), key=lambda item: (item["display_name"].casefold(), item["key"])), "unlinked_attendees": unlinked}
