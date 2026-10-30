from __future__ import annotations

import json
import re
from collections.abc import Sequence
from uuid import UUID

from services.meetings.participants import email_participant, speaker_key

CONTEXT_BYTES = 32_000
TARGET_BYTES = 16_000
REQUEST_BYTES = 48_000


class SpeakerContextTooLarge(ValueError):
    pass


class SpeakerIdentityConflict(ValueError):
    pass


def encoded_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def names(person: dict) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in [person.get("name") or person.get("email"), *person.get("aliases", []), *person.get("nicknames", [])]
                             if isinstance(value, str) and value.strip()))


def emails(person: dict) -> list[str]:
    return list(dict.fromkeys(email_participant(value)["email"] for value in [person.get("email"), *person.get("emails", [])] if value))


def identities(rows: list[dict]) -> list[dict]:
    normalized = []
    for raw in rows:
        labels = names(raw)
        if not labels:
            continue
        person = {"name": labels[0][:200]}
        if len(labels) > 1:
            person["aliases"] = labels[1:]
        addresses = emails(raw)
        if addresses:
            person["email"] = addresses[0]
            if len(addresses) > 1:
                person["emails"] = addresses
        if raw.get("profile_id"):
            person["profile_id"] = str(UUID(raw["profile_id"]))
        for key in ("revision", "metadata", "metadata_provenance"):
            if raw.get(key) is not None:
                person[key] = raw[key]
        normalized.append(person)
    groups = []
    for person in sorted(normalized, key=lambda row: not bool(row.get("profile_id"))):
        # Group canonical aliases first, then attach roster spellings by proven email.
        matching = [group for group in groups if person.get("profile_id") and group.get("profile_id") == person["profile_id"]
                    or set(emails(person)) & set(emails(group))]
        if len(matching) > 1 or matching and person.get("profile_id") and matching[0].get("profile_id") not in {None, person["profile_id"]}:
            raise SpeakerIdentityConflict("A supplied email belongs to conflicting canonical profiles")
        if not matching:
            groups.append(dict(person))
            continue
        group = matching[0]
        if person.get("revision") is not None and group.get("revision") is not None and person["revision"] != group["revision"]:
            raise SpeakerIdentityConflict("Conflicting revisions for the same canonical speaker context")
        for key in ("revision", "metadata", "metadata_provenance"):
            if key in person:
                group[key] = person[key]
        labels = list(dict.fromkeys([*names(group), *names(person)]))
        addresses = list(dict.fromkeys([*emails(group), *emails(person)]))
        group.update(aliases=labels[1:])
        if addresses:
            group.update(email=addresses[0], emails=addresses)
    result = []
    for person in normalized:
        group = next((group for group in groups if person.get("profile_id") and group.get("profile_id") == person["profile_id"]
                      or set(emails(person)) & set(emails(group))), person)
        compact = {key: value for key, value in group.items() if value not in ([], None)}
        if compact.get("emails") == [compact.get("email")]:
            compact.pop("emails", None)
        if compact not in result:
            result.append(compact)
    return result


def candidates(snapshot: dict, segments: Sequence[dict] = ()) -> list[dict]:
    metadata = snapshot.get("metadata") or {}
    rows = [*snapshot.get("manual_participants", []), metadata.get("owner") or {}, *metadata.get("attendees", []),
            *metadata.get("calendar_event", {}).get("invitees", []),
            *(speaker for segment in segments if (speaker := segment.get("speaker") or {}) and (
                speaker.get("email") or speaker.get("name") and speaker["name"].casefold() not in {"me", "them", "unknown", "unknown speaker", "unidentified speaker"}
                and not re.fullmatch(r"speaker[ _-]*\d+", speaker["name"], re.IGNORECASE))), *snapshot.get("identity_candidates", [])]
    return identities(rows)[:200]


def window_context(snapshot: dict, segments: list[dict], offset: int, previous: list[dict]) -> tuple[list[dict], list[dict]]:
    opening = [{**segment, "context_source": "opening"} for segment in segments[:40]]
    # Introductions and named address should survive a long opening with greetings.
    labels = [label.casefold() for person in candidates(snapshot) for label in names(person)]
    opening.sort(key=lambda segment: not (re.search(r"\b(?:i'm|i am|my name is|this is)\b", segment["text"], re.IGNORECASE)
                                          or any(label in segment["text"].casefold() for label in labels)))
    adjacent = [{**segment, "context_source": "adjacent"} for segment in segments[max(0, offset - 3):offset]]
    by_id = {segment["id"]: segment for segment in segments}
    positions = {segment["id"]: index for index, segment in enumerate(segments)}
    anchors, human_ids = [], set()
    for manual in snapshot.get("manual_participants", []):
        mapped = [segment for segment in segments if segment["id"] == manual.get("segment_id") or (
            manual.get("speaker_key") and speaker_key(segment.get("speaker") or {}) == manual["speaker_key"])]
        human_ids.update(segment["id"] for segment in mapped)
        # A channel assignment is authoritative, but one quote is enough context.
        if mapped:
            source = min(mapped, key=lambda segment: abs(positions[segment["id"]] - offset))
            anchors.append({**{key: manual[key] for key in ("name", "email", "profile_id") if manual.get(key)},
                            "segment_id": source["id"], "text": source["text"], "source": "human", "confidence": "high"})
    for source, rows in (("committed", snapshot.get("statement_attributions", [])), ("earlier_window", list(reversed(previous)))):
        for item in rows:
            segment = by_id.get(item["segment_id"])
            if segment and item.get("confidence") == "high" and segment["id"] not in human_ids:
                anchors.append({**{key: item[key] for key in ("name", "email", "profile_id") if item.get(key)},
                                "segment_id": segment["id"], "text": segment["text"], "source": source, "confidence": "high"})
    return [*opening, *adjacent], anchors


def quoted_context(snapshot: dict, targets: list[dict], context: list[dict], anchors: list[dict]) -> dict:
    data = {"meeting": {}, "target_statements": targets, "read_only_context": [],
            "read_only_identity_anchors": [], "candidates": [], "omitted": {}}
    owner = candidates({"metadata": {"owner": (snapshot.get("metadata") or {}).get("owner") or {}}})
    if owner:
        data["meeting"]["owner"] = owner[0]
    if encoded_size(data) > CONTEXT_BYTES:
        raise SpeakerContextTooLarge("Speaker target statements exceed the quoted context budget")

    def pack(key: str, rows: list[dict], limit: int, budget: int) -> None:
        selected = []
        for row in rows:
            trial = [*selected, row]
            if len(trial) > limit or encoded_size(trial) > budget:
                continue
            data[key] = trial
            # Reserve room for bounded omission counts and later envelope fields.
            if encoded_size(data) > CONTEXT_BYTES - 512:
                data[key] = selected
                continue
            selected = trial
        data["omitted"][key] = max(0, len(rows) - len(selected))

    target_ids = {segment["id"] for segment in targets}
    opening = [row for row in context if row.get("context_source") == "opening" and row["id"] not in target_ids]
    pack("read_only_context", opening, 40, 8_000)
    pack("read_only_identity_anchors", anchors, 24, 8_000)
    known = candidates(snapshot, [*targets, *data["read_only_context"]])
    pack("candidates", known, 200, 8_000)
    for key, value in (("title", snapshot.get("title")), ("summary_excerpt", (snapshot.get("summary_text") or "")[:4000])):
        if value and encoded_size({**data, "meeting": {**data["meeting"], key: value}}) <= CONTEXT_BYTES - 256:
            data["meeting"][key] = value
    adjacent = [row for row in context if row.get("context_source") != "opening" and row["id"] not in target_ids]
    existing = data["read_only_context"]
    pack("read_only_context", [*existing, *[row for row in adjacent if row["id"] not in {item["id"] for item in existing}]], 43, 11_000)
    data["omitted"]["read_only_context"] = len({row["id"] for row in context} - target_ids) - len(data["read_only_context"])
    return data
