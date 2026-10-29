from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid5

_PARTICIPANTS = UUID("774b6f1c-6417-5419-9820-2169a7320256")
_UNNAMED = {"me", "them", "unknown", "unknown speaker", "unidentified speaker"}


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _email(value) -> str | None:
    value = _text(value).casefold()
    if (value.count("@") != 1 or any(char.isspace() or char in "<>" for char in value)
            or not all(value.split("@")) or len(value) > 320):
        return None
    return value


def meeting_participants(snapshot: dict, segments: list[dict]) -> list[dict]:
    meeting_id = str(UUID(snapshot["id"]))
    roster = {}
    for attendee in snapshot.get("metadata", {}).get("attendees", []):
        name, email = _text(attendee.get("name")), _email(attendee.get("email"))
        if name and email:
            roster.setdefault(name.casefold(), set()).add(email)
    participants = {}
    for segment in segments:
        speaker = segment.get("speaker") or {}
        name = _text(speaker.get("name"))
        label = _text(speaker.get("diarization_label"))
        if re.fullmatch(r"speaker[ _-]*\d+", name, re.IGNORECASE):
            label, name = label or name, ""
        if name.casefold() in _UNNAMED:
            name = ""
        email = _email(speaker.get("email"))
        matches = roster.get(name.casefold(), set()) if name else set()
        if email is None and len(matches) == 1:
            email = next(iter(matches))
        if email:
            key = f"email:{email}"
        elif name or label:
            identity = {"name": name, "diarization_label": label,
                        "source": _text(speaker.get("source")), "attribution": _text(speaker.get("attribution"))}
            fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            key = f"meeting:{meeting_id}:{fingerprint}"
        else:
            # A shared microphone without a name/label cannot identify a person.
            continue
        participant_id = str(uuid5(_PARTICIPANTS, key))
        person = participants.setdefault(participant_id, {
            "id": participant_id, "identity_key": key, "display_name": name or email or label,
            "email": email, "identity_scope": "email" if email else "meeting", "segment_ids": [],
        })
        if segment["id"] not in person["segment_ids"]:
            person["segment_ids"].append(segment["id"])
    return list(participants.values())
