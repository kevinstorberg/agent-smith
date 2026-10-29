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


def _participant(key: str, name: str, email: str | None, scope: str, *, profile_id: str | None = None) -> dict:
    return {
        "id": profile_id or str(uuid5(_PARTICIPANTS, key)), "identity_key": key, "display_name": name,
        "email": email, "identity_scope": scope, "segment_ids": [],
    }


def email_participant(email: str, display_name: str = "") -> dict:
    normalized = _email(email)
    if normalized is None:
        raise ValueError("Participant email must be a valid address")
    if not isinstance(display_name, str) or len(display_name) > 1000:
        raise ValueError("Participant display name must be a string of at most 1000 characters")
    return _participant(f"email:{normalized}", _text(display_name) or normalized, normalized, "email")


def speaker_key(speaker: dict) -> str:
    if not isinstance(speaker, dict):
        raise ValueError("Speaker must be an object")
    original = {key: _text(speaker.get(key)) for key in ("name", "email", "diarization_label", "source", "attribution")}
    original["email"] = original["email"].casefold()
    return hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()


def current_manual(participants: list[dict], segments: list[dict]) -> list[dict]:
    keys = {speaker_key(segment.get("speaker") or {}) for segment in segments}
    ids = {segment["id"] for segment in segments}
    return [entry for entry in participants if (not entry.get("speaker_key") or entry["speaker_key"] in keys)
            and (not entry.get("segment_id") or entry["segment_id"] in ids)]


def _manual_roster(snapshot: dict, segments: list[dict]) -> tuple[dict, dict, dict]:
    manual = snapshot.get("manual_participants", [])
    if not isinstance(manual, list) or len(manual) > 200:
        raise ValueError("Manual participants must contain at most 200 entries")
    if not manual:
        return {}, {}, {}
    observed = {speaker_key(segment.get("speaker") or {}) for segment in segments}
    observed_ids = {segment["id"] for segment in segments}
    overrides, statements, roster = {}, {}, {}
    for entry in manual:
        if not isinstance(entry, dict):
            raise ValueError("Manual participant must be an object")
        name = _text(entry.get("name"))
        if not name or len(name) > 1000:
            raise ValueError("Manual participant requires a name of at most 1000 characters")
        participant = None
        email = entry.get("email")
        if email is not None and (not isinstance(email, str) or (email.strip() and _email(email) is None)):
            raise ValueError("Manual participant email must be a valid address")
        email = _email(email)
        profile_id = entry.get("profile_id")
        if profile_id is not None:
            try:
                profile_id = str(UUID(profile_id)) if isinstance(profile_id, str) else None
            except ValueError:
                profile_id = None
            if profile_id is None:
                raise ValueError("Manual participant profile ID must be a UUID")
            participant = _participant(f"profile:{profile_id}", name, email, "email" if email else "meeting", profile_id=profile_id)
        elif email:
            participant = email_participant(email, name)
        if participant:
            participant = {**participant, "identity_source": "manual_assignment"}
        key = entry.get("speaker_key")
        segment_id = entry.get("segment_id")
        if key is not None and segment_id is not None:
            raise ValueError("Choose a statement or a transcript speaker, not both")
        if segment_id is not None:
            if not isinstance(segment_id, str) or segment_id not in observed_ids:
                raise ValueError("Manual participant references an unknown transcript statement")
            if segment_id in statements:
                raise ValueError("A transcript statement cannot have multiple manual participants")
            statements[segment_id] = {"name": name, "participant": participant}
        if key is not None:
            if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key) or key not in observed:
                raise ValueError("Manual participant references an unknown transcript speaker")
            if key in overrides:
                raise ValueError("A transcript speaker cannot have multiple manual participants")
            overrides[key] = {"name": name, "participant": participant}
        elif participant and segment_id is None:
            roster.setdefault(name.casefold(), {})[participant["id"]] = participant
    return overrides, statements, roster


def _speaker_participant(meeting_id: str, speaker: dict, roster: dict, override: dict | None) -> dict | None:
    if override and override["participant"]:
        return override["participant"]
    if override:
        speaker = {**speaker, "name": override["name"], "email": None}
    name = _text(speaker.get("name"))
    label = _text(speaker.get("diarization_label"))
    if re.fullmatch(r"speaker[ _-]*\d+", name, re.IGNORECASE):
        label, name = label or name, ""
    if name.casefold() in _UNNAMED:
        name = ""
    email = _email(speaker.get("email"))
    matches = roster.get(name.casefold(), {}) if name else {}
    if email:
        return {**email_participant(email, name), "identity_source": "speaker_email"}
    if len(matches) == 1:
        match = next(iter(matches.values()))
        return {**match, "display_name": name, "segment_ids": [], "identity_source": match.get("identity_source", "attendee_match")}
    if name or label:
        identity = {"name": name, "diarization_label": label,
                    "source": _text(speaker.get("source")), "attribution": _text(speaker.get("attribution"))}
        fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return {**_participant(f"meeting:{meeting_id}:{fingerprint}", name or label, None, "meeting"),
                "identity_source": "manual_assignment" if override else "speaker_label"}
    # A shared microphone needs explicit human attribution to identify a person.
    return None


def meeting_participants(snapshot: dict, segments: list[dict]) -> list[dict]:
    meeting_id = str(UUID(snapshot["id"]))
    overrides, statements, roster = _manual_roster(snapshot, segments)
    for attendee in snapshot.get("metadata", {}).get("attendees", []):
        name, email = _text(attendee.get("name")), _email(attendee.get("email"))
        if name and email:
            participant = email_participant(email, name)
            roster.setdefault(name.casefold(), {}).setdefault(participant["id"], participant)
    participants = {}
    automatic = {item["segment_id"]: item for item in snapshot.get("statement_attributions", []) if item.get("confidence") == "high"}
    for segment in segments:
        speaker = segment.get("speaker") or {}
        override = statements.get(segment["id"]) or overrides.get(speaker_key(speaker))
        participant = _speaker_participant(meeting_id, speaker, roster, override)
        named = _text(speaker.get("name"))
        provider_identity = bool(_email(speaker.get("email")) or named and named.casefold() not in _UNNAMED
                                 and not re.fullmatch(r"speaker[ _-]*\d+", named, re.IGNORECASE))
        generated = automatic.get(segment["id"])
        if generated and not override and not provider_identity:
            identified = {"name": generated["name"], "email": generated.get("email"), "source": "statement_attribution"}
            person = None
            if generated.get("email"):
                person = email_participant(generated["email"], generated["name"])
            if generated.get("profile_id"):
                profile_id = str(UUID(generated["profile_id"]))
                person = _participant(f"profile:{profile_id}", generated["name"], generated.get("email"),
                                      "email" if generated.get("email") else "meeting", profile_id=profile_id)
            participant = _speaker_participant(meeting_id, identified, {}, {"name": generated["name"], "participant": person})
            if participant:
                participant = {**participant, "identity_source": "automatic_statement"}
        if participant is None:
            continue
        person = participants.setdefault(participant["id"], {**participant, "segment_ids": []})
        if segment["id"] not in person["segment_ids"]:
            person["segment_ids"].append(segment["id"])
    return list(participants.values())
