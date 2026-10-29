from __future__ import annotations

from services.meetings import profile_db
from services.meetings.participants import current_manual, meeting_participants


def effective_speakers(cur, snapshot: dict, segments: list[dict]) -> dict[str, dict]:
    snapshot = {**snapshot, "manual_participants": current_manual(snapshot.get("manual_participants", []), segments)}
    raw = meeting_participants(snapshot, segments)
    sources = {segment_id: person.get("identity_source", "speaker_label") for person in raw for segment_id in person["segment_ids"]}
    catalog = profile_db.resolve_participants(raw, cursor=cur)
    result = {}
    for person in catalog:
        if person.get("deleted"):
            continue
        effective = {
            "profile_id": person["id"] if "deleted" in person else None,
            "display_name": person["display_name"], "email": person.get("email"),
            "source": person.get("identity_source", "speaker_label"),
        }
        for segment_id in person["segment_ids"]:
            result[segment_id] = {**effective, "source": sources[segment_id]}
    return result
