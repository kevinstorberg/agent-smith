"""Read old named assessments and directed records as one card per person."""
from __future__ import annotations

import hashlib
import json
import re

from services.meetings.profile_fields import MAX_NOTE_LENGTH, normalized_text

_HEADER = re.compile(r"(?m)(?:^|\n)[ \t]*(?P<format>#{1,6}[ \t]+|\*\*)?(?P<title>[^\n:]{1,240}):(?:\*\*)?[ \t]*")
_TITLE = re.compile(r"(?m)(?:^|\n)[ \t]*(?P<format>#{1,6}[ \t]+|\*\*)(?P<title>[^\n:]{1,240}?)(?:\*\*)?[ \t]*(?:\n|$)")
_INLINE = re.compile(r"(?<=[.!?])\s+(?P<title>[A-Z][\w'’.-]*(?:[ \t]+[A-Z][\w'’.-]*){0,3}):[ \t]*")
_ARROW = re.compile(r"\s*(?:→|->)\s*")
_NON_NAMES = {"overall", "context", "notes", "relationship", "relationships", "summary", "evidence", "observations", "assessment", "perceptions", "uncertainty"}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def person_key(name: str, profile_id: str | None) -> str:
    return f"profile:{profile_id}" if profile_id else f"name:{digest(normalized_text(name))}"


def identity_index(identities: list[dict]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for person in identities:
        for name in [person["display_name"], *person.get("nicknames", []), *person.get("aliases", [])]:
            if name:
                result.setdefault(normalized_text(name), set()).add(str(person["id"]))
    return result


def _name(title: str) -> str:
    title = title.strip().strip("*_`\"'“”")
    return re.sub(r"\s+\([^)]*\)\s*$", "", title).strip().strip("*_`\"'“”")


def _inside_quote(text: str, end: int) -> bool:
    quote = None
    code = None
    for match in re.finditer(r"`+|[\"'“”‘’]", text[:end]):
        token = match.group()
        if match.start() and text[match.start() - 1] == "\\":
            continue
        if token.startswith("`"):
            code = None if code == token else token if code is None else code
            continue
        if code is not None:
            continue
        before = text[match.start() - 1] if match.start() else ""
        after = text[match.end()] if match.end() < len(text) else ""
        if quote == token:
            quote = None
            continue
        if token in {"'", "’"} and (before.isalnum() or not after or after.isspace() or token == "’"):
            continue
        if quote is None:
            quote = {"“": "”", "‘": "’"}.get(token, token)
    return quote is not None or code is not None


def parse_legacy(text: str, owner: dict, identities: list[dict]) -> dict:
    if not isinstance(text, str) or len(text) > MAX_NOTE_LENGTH:
        raise ValueError("Legacy relationship analysis exceeds the stored section limit")
    known = identity_index(identities)
    owner_names = {normalized_text(value) for value in [owner["display_name"], *owner.get("nicknames", [])]}
    owner_names.update(normalized_text(alias) for person in identities if str(person["id"]) == str(owner["id"]) for alias in person.get("aliases", []))
    first = normalized_text(owner["display_name"].split()[0])
    if sum(normalized_text(person["display_name"].split()[0]) == first for person in identities) == 1:
        owner_names.add(first)
    endpoints: dict[str, set[str]] = {}
    for person in identities:
        if person.get("endpoint"):
            endpoints.setdefault(normalized_text(person["display_name"].split()[0]), set()).add(str(person["id"]))
    labels = set(known) | {normalized_text(person["display_name"].split()[0]) for person in identities}
    headers = []
    candidates = [(match, False) for pattern in (_HEADER, _TITLE) for match in pattern.finditer(text)] + [(match, True) for match in _INLINE.finditer(text)]
    for match, inline in sorted(candidates, key=lambda item: item[0].start()):
        if _inside_quote(text, match.start()):
            continue
        title = match["title"].strip().strip("*_`\"'“”")
        arrow = _ARROW.search(title)
        if arrow:
            left = title[:arrow.start()].rsplit("(", 1)[-1].strip()
            right = title[arrow.end():].strip()
            if "(" in title[:arrow.start()]:
                right = right.rsplit(")", 1)[0].strip()
            if normalized_text(_name(left)) in owner_names:
                name = _name(right)
            elif normalized_text(_name(right)) in owner_names:
                outer = title.split("(", 1)[0].strip() if "(" in title else ""
                name = _name(outer or left)
            else:
                continue
        else:
            name = _name(title)
            formatted = not inline and bool(match["format"])
            if normalized_text(name) not in labels and not formatted:
                continue
        if not name or len(name) > 200 or normalized_text(name) in owner_names | _NON_NAMES:
            continue
        matches = known.get(normalized_text(name), set()) or endpoints.get(normalized_text(name), set())
        profile_id = next(iter(matches)) if len(matches) == 1 else None
        if profile_id == str(owner["id"]):
            continue
        start = match.start()
        if headers and start < headers[-1]["body_start"]:
            continue
        headers.append({"name": name, "profile_id": profile_id, "start": start, "body_start": match.end()})
    parts = []
    for index, header in enumerate(headers):
        end = headers[index + 1]["start"] if index + 1 < len(headers) else len(text)
        part = {**header, "end": end, "notes": text[header["body_start"]:end].strip()}
        part["key"] = digest(text[header["start"]:end].strip())
        parts.append(part)
    unresolved = text[:headers[0]["start"]] if headers else text
    assert sum(part["end"] - part["start"] for part in parts) + len(unresolved) == len(text)
    return {"parts": parts, "unresolved": unresolved.strip()}


def imports(history: list[dict], owner_ids: list[str]) -> list[dict]:
    result = []
    def visit(value):
        if isinstance(value, dict):
            if value.get("action") == "legacy_import" and value.get("profile_id") in owner_ids:
                result.append(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(history)
    return result


def import_keys(history: list[dict], owner_id: str | list[str]) -> set[str]:
    return {key for receipt in imports(history, [owner_id] if isinstance(owner_id, str) else owner_id) for key in receipt.get("keys", [])}


def legacy_state(owner: dict) -> str:
    return digest([owner.get("section_notes", {}).get("relationships"), owner.get("section_evidence", {}).get("relationships")])


def project(owner: dict, edges: list[dict], identities: list[dict], *, raw_owner: dict | None = None,
            receipt_history: list[dict] | None = None) -> dict:
    raw_owner = raw_owner or owner
    owner_id = str(owner["id"])
    text = owner.get("section_notes", {}).get("relationships", "")
    parsed = parse_legacy(text, owner, identities)
    names = {str(person["id"]): person["display_name"] for person in identities}
    owner_ids = owner.get("_card_owner_ids", [owner_id])
    consumed = import_keys(receipt_history or [], owner_ids)
    for edge in edges:
        consumed.update(import_keys(edge.get("history", []), owner_ids))
    groups: dict[str, dict] = {}
    for part in parsed["parts"]:
        if part["key"] in consumed:
            continue
        key = person_key(part["name"], part["profile_id"])
        groups.setdefault(key, {"id": key, "name": names.get(part["profile_id"], part["name"]), "profile_id": part["profile_id"], "parts": [], "edges": []})["parts"].append(part)
    for edge in edges:
        outgoing = str(edge["subject_id"]) == owner_id
        other = edge.get("target_id") if outgoing else str(edge["subject_id"])
        other = str(other) if other is not None else None
        name = edge["target_name"] if outgoing else edge["subject_name"]
        key = person_key(name, other)
        group = groups.setdefault(key, {"id": key, "name": names.get(other, name), "profile_id": other, "parts": [], "edges": []})
        group["edges"].append(edge)
    proof = owner.get("section_evidence", {}).get("relationships", {})
    global_clear = proof.get("human") is True and not text
    cards, internals = [], {}
    for key, group in groups.items():
        related = sorted(group["edges"], key=lambda edge: str(edge["id"]))
        active_outgoing = [edge for edge in related if str(edge["subject_id"]) == owner_id and not edge.get("dismissed")]
        if any(edge.get("dismissed") for edge in related) and not active_outgoing:
            continue
        related = [edge for edge in related if not edge.get("dismissed")]
        outgoing = [edge for edge in related if str(edge["subject_id"]) == owner_id]
        incoming = [edge for edge in related if str(edge["subject_id"]) != owner_id]
        def human(edge):
            source = edge.get("analysis_evidence", {})
            return source.get("human") is True or source.get("origin") == "human"
        def attempted(edge):
            source = edge.get("analysis_evidence", {})
            return bool(source.get("generated_at") or source.get("status") in {"supported", "stale"} or edge.get("notes"))
        legacy = group["parts"]
        own_human = next((edge for edge in outgoing if human(edge)), None)
        other_human = next((edge for edge in incoming if human(edge)), None)
        own_attempt = next((edge for edge in outgoing if attempted(edge)), None)
        other_attempt = next((edge for edge in incoming if attempted(edge)), None)
        legacy_human = bool(legacy and proof.get("human"))
        selected = own_human or (None if legacy_human or global_clear else other_human or own_attempt)
        use_legacy = selected is None and bool(legacy) and not global_clear
        if selected is None and not use_legacy and not global_clear:
            selected = other_attempt or (outgoing or incoming or [None])[0]
        selected_proof = selected.get("analysis_evidence", {}) if selected else proof if use_legacy or global_clear else {}
        notes = selected.get("notes", "") if selected else "\n\n".join(part["notes"] for part in legacy) if use_legacy else ""
        clears = global_clear and not (own_human and any(receipt.get("legacy_state") == legacy_state(raw_owner)
            for receipt in imports(own_human.get("history", []), owner_ids)))
        if clears:
            notes = ""
            selected_proof = proof
        if selected and selected.get("analysis_stale"):
            status = "stale"
        else:
            status = selected_proof.get("status", "supported" if notes or selected_proof.get("human") else "pending")
            if not notes and not selected_proof.get("human") and not selected_proof.get("generated_at") and status == "insufficient_evidence":
                status = "pending"
        coverage = selected_proof.get("coverage", {"claim_count": selected_proof.get("claim_count", 0), "meeting_count": 0})
        sources = [{"profile_id": str(edge["subject_id"]), "target_id": str(edge["target_id"]), "count": edge.get("claim_count", 0)} for edge in related if edge.get("target_id") and edge.get("claim_count", 0)]
        signature = {"key": key, "notes": notes, "selected": selected.get("id") if selected else "legacy", "proof": selected_proof,
                     "edges": [{field: edge.get(field) for field in ("id", "revision", "subject_id", "target_id", "target_name", "dismissed", "analysis_evidence", "analysis_stale", "source_version")} for edge in related],
                     "identities": [owner_id, owner["display_name"], group["profile_id"], group["name"]],
                     "legacy": [raw_owner.get("revision"), raw_owner.get("section_evidence", {}).get("relationships"), [part["key"] for part in legacy]] if legacy or global_clear else None}
        card = {"id": key, "name": group["name"], "profile_id": group["profile_id"], "notes": notes,
                "label": selected.get("label", "") if selected else "", "version": digest(signature),
                "human": selected_proof.get("human") is True, "status": status, "coverage": coverage, "evidence_links": sources}
        cards.append(card)
        internals[key] = {"card": card, "parts": legacy, "edges": related, "selected": selected, "legacy": use_legacy, "global_clear": global_clear}
    unassigned_key = digest(["unassigned", parsed["unresolved"]])
    unassigned = {"notes": parsed["unresolved"], "version": digest([unassigned_key, raw_owner.get("revision"), proof])} if parsed["unresolved"] and unassigned_key not in consumed else None
    return {"relationship_cards": sorted(cards, key=lambda card: (normalized_text(card["name"]), card["id"])),
            "relationship_unassigned": unassigned, "_cards": internals, "_unassigned_key": unassigned_key}
