from __future__ import annotations

import asyncio
import json
import re
from typing import Annotated, Literal
from uuid import UUID

from langchain_core.tools import tool
from pydantic import Field

from services.meetings.analysis import AnalysisContext, MeetingAnalysisError, run_analysis
from services.meetings.outputs import Evidence, _Output
from services.meetings.participants import email_participant
from services.meetings.speaker_prompt import SYSTEM_PROMPT
from services.meetings.service import run_db

WINDOW_CHARACTERS = 12_000
WINDOW_STATEMENTS = 40


class SpeakerAnalysisError(MeetingAnalysisError):
    pass


class StatementAssignment(_Output):
    segment_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    profile_id: str | None = Field(default=None, max_length=200)
    confidence: Literal["high", "medium", "low"]
    rationale: str = Field(min_length=1, max_length=1000)
    evidence: list[Evidence] = Field(min_length=1, max_length=4)


class SpeakerSubmission(_Output):
    assignments: list[StatementAssignment] = Field(max_length=WINDOW_STATEMENTS)
    reason: str = Field(default="", max_length=1000)


def candidates(snapshot: dict) -> list[dict]:
    metadata = snapshot.get("metadata") or {}
    rows = [*snapshot.get("manual_participants", []), metadata.get("owner") or {}, *metadata.get("attendees", []),
            *metadata.get("calendar_event", {}).get("invitees", []), *snapshot.get("identity_candidates", [])]
    result = {}
    for person in rows:
        name = (person.get("name") or person.get("email") or "").strip()
        if not name:
            continue
        candidate = {"name": name[:200]}
        if person.get("email"):
            try:
                candidate["email"] = email_participant(person["email"])["email"]
            except ValueError:
                continue
        if person.get("profile_id"):
            candidate["profile_id"] = str(UUID(person["profile_id"]))
        result.setdefault(json.dumps(candidate, sort_keys=True), candidate)
    return list(result.values())[:200]


def target_window(segments: list[dict], offset: int) -> tuple[list[dict], int]:
    target, size, end = [], 0, offset
    for segment in segments[offset:]:
        length = len(segment["text"])
        if length > WINDOW_CHARACTERS:
            if target:
                break
            return [], offset + 1
        if len(target) == WINDOW_STATEMENTS or target and size + length > WINDOW_CHARACTERS:
            break
        target.append(segment)
        size += length
        end += 1
    return target, end


def validate_assignments(assignments: list[dict], targets: list[dict], context: list[dict], known: list[dict], anchors: list[dict]) -> list[dict]:
    target_ids = {segment["id"] for segment in targets}
    texts = {segment["id"]: segment["text"] for segment in [*context, *targets]}
    identities = [*known, *anchors]
    result, seen = [], set()
    for raw in assignments:
        item = StatementAssignment.model_validate(raw).model_dump()
        segment_id, name = item["segment_id"], item["name"].strip()
        if segment_id not in target_ids or segment_id in seen:
            raise ValueError("Assign each target statement at most once; context statements are read only")
        if not name or not item["rationale"].strip():
            raise ValueError("An assignment requires a name and a concise rationale")
        for proof in item["evidence"]:
            if not proof["quote"].strip() or proof["quote"] not in texts.get(proof["segment_id"], ""):
                raise ValueError("Speaker evidence must quote exact supplied transcript text")
        matches = [person for person in identities if (person.get("name") or "").casefold() == name.casefold()]
        if item.get("email"):
            item["email"] = email_participant(item["email"])["email"]
            matches = [person for person in matches if person.get("email") == item["email"]]
            if not matches:
                raise ValueError("Use only a supplied candidate's known email for that same person")
        if item.get("profile_id"):
            item["profile_id"] = str(UUID(item["profile_id"]))
            if not any(person.get("profile_id") == item["profile_id"] for person in matches):
                raise ValueError("Use only a supplied canonical profile ID for that same candidate")
        if not matches:
            introduction = re.compile(r"\b(?:i(?:'m| am)|my name is|this is)\s+" + re.escape(name) + r"\b", re.IGNORECASE)
            if not any(proof["segment_id"] == segment_id and introduction.search(proof["quote"]) for proof in item["evidence"]):
                raise ValueError("A new meeting-scoped person needs an explicit self-introduction in their own statement")
        item["name"] = name
        result.append(item)
        seen.add(segment_id)
    return result


async def identify_statements(snapshot: dict, targets: list[dict], *, context: list[dict], anchors: list[dict], deadline: float) -> dict:
    known = candidates(snapshot)
    researched = []
    known_ids = {person["profile_id"] for person in [*known, *anchors] if person.get("profile_id")}
    analysis = AnalysisContext(snapshot, targets, [], require_memory_search=False)

    @tool
    async def search_known_profiles(
        query: Annotated[str, Field(max_length=200)] = "",
        profile_id: str | None = None,
    ) -> str:
        """Search and read up to three known profile contexts by name, email, nickname, company or job role in one call."""
        from services.meetings import speaker_profiles

        if profile_id is not None:
            try:
                profile_id = str(UUID(profile_id))
            except ValueError:
                return json.dumps({"error": "Profile ID must be a UUID"})
        if profile_id and query.strip():
            return json.dumps({"error": "Use a search query or an exact profile ID, not both"})
        try:
            envelope = await run_db(speaker_profiles.read_contexts, query, profile_id, known_ids)
        except Exception as error:
            return json.dumps({"error": "Known profile context read failed", "error_type": type(error).__name__})
        discoveries = speaker_profiles.identity_candidates(envelope.get("items", []))
        researched.extend(discoveries)
        known_ids.update(person["profile_id"] for person in discoveries)
        return json.dumps(envelope, ensure_ascii=False)

    @tool(args_schema=SpeakerSubmission)
    async def stage_speakers(assignments: list[StatementAssignment], reason: str = "") -> str:
        """Stage grounded identities for target statements; adjacent context is read only."""
        analysis.collector.clear()
        try:
            validated = validate_assignments([item.model_dump() for item in assignments], targets, context, [*known, *researched], anchors)
        except ValueError as error:
            return json.dumps({"error": str(error)})
        if not validated and not reason.strip():
            return json.dumps({"error": "Explain why these target statements remain unresolved"})
        analysis.collector.update(assignments=validated, reason=reason.strip())
        used_ids = {item["profile_id"] for item in validated if item.get("profile_id")}
        if used_ids:
            analysis.collector["resolved_candidates"] = [person for person in researched if person["profile_id"] in used_ids]
        return json.dumps({"staged": len(validated)})

    data = {"meeting": {key: snapshot.get(key) for key in ("title", "metadata", "manual_participants")},
            "candidates": known, "target_statements": targets, "read_only_context": context,
            "read_only_identity_anchors": anchors}
    search_known_profiles.handle_validation_error = "Profile context read rejected: use a query of at most 200 characters or a supplied profile ID."
    return await run_analysis(analysis, model_role="meeting_speaker", system_prompt=SYSTEM_PROMPT,
                              tools=[search_known_profiles, analysis.configure_stage(stage_speakers)], data=data, label="Speaker",
                              error_class=SpeakerAnalysisError, deadline=min(deadline, asyncio.get_running_loop().time() + 30),
                              model_call_limit=3, tool_call_limit=4)
