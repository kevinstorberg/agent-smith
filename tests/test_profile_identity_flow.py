import asyncio
import copy
import json
from dataclasses import replace

import pytest

from services.db import get_connection
from services.graphs.runtime import dispatch as graph_dispatch
from services.meetings import db, digestion_db, management_db, profile_db
from services.personas import service as enrichment
from services.meetings.participants import email_participant, speaker_key
from services.meetings.types import TranscriptSegment
from tests.test_meeting_memory_flow import agents as agents, feed as feed
from tests.test_meeting_profile_flow import profile_due
from tests.test_meeting_sync import note, source as source


async def ingest_and_profile(inputs):
    imported = json.loads(await graph_dispatch("meeting_ingest", inputs))
    if inputs.get("digest") is False:
        return json.dumps(imported)
    persona = json.loads(await graph_dispatch("persona", {key: value for key, value in inputs.items() if key == "source"}))
    return json.dumps({**imported, **persona})


@pytest.fixture
def identities(source, feed):
    people = [email_participant(f"{name}-{source.account_key}@example.invalid", "Alex") for name in ("first", "second")]
    feed.summaries = {}
    yield people
    with get_connection() as conn, conn.cursor() as cur:
        keys = tuple(person["id"] for person in people)
        cur.execute("DELETE FROM participant_profiles WHERE merged_into IN %s", (keys,))
        cur.execute("DELETE FROM participant_profiles WHERE id IN %s", (keys,))


@pytest.fixture
def profile_agent(agents, monkeypatch, extraction_only):
    from services.meetings import profile_analysis

    calls = []

    async def analyze(snapshot, window, previous, *, participants, profiles, memories, deadline, previous_metadata=None):
        calls.append(copy.deepcopy({"snapshot": snapshot, "participants": participants, "profiles": profiles, "previous": previous}))
        if any(profile.get("deleted") for profile in profiles):
            return {"items": [], "reason": "Deleted identities remain deleted"}
        return {"items": [{
            "subject_id": next(person["id"] for person in participants if segment["id"] in person["segment_ids"]),
            "target_id": None, "category": "priority", "epistemic": "self_report", "confidence": "high",
            "content": segment["text"], "rationale": "Direct statement",
            "evidence": [{"segment_id": segment["id"], "quote": segment["text"]}],
        } for segment in window], "reason": ""}

    monkeypatch.setattr(profile_analysis, "analyze_profiles", analyze)
    return calls, analyze


def add_meeting(feed, external_id, *people):
    feed.summaries[external_id] = replace(note(external_id), metadata={"attendees": [
        {"name": person["display_name"], "email": person["email"]} for person in people
    ]})
    feed.segments = tuple(TranscriptSegment(f"I prioritize dependable {external_id} work {index}.", {
        "name": person["display_name"], "email": person["email"],
    }) for index, person in enumerate(people))


def meeting_id(source, external_id):
    return next(row["id"] for row in db.list_summaries(source=source.name)["items"] if row["external_id"] == external_id)


async def seed_profiles(source, feed, identities):
    for index, person in enumerate(identities):
        add_meeting(feed, f"initial-{index}", person)
        result = json.loads(await ingest_and_profile({"source": source.name}))
        assert result["profiles"]["outcome"] == "done"
    return [profile_db.get_profile(person["id"]) for person in identities]


def merge(profiles):
    source, target = profiles
    return profile_db.merge_profiles(source["id"], target["id"], source["revision"], target["revision"])


@pytest.mark.asyncio
async def test_future_meeting_uses_losing_email_as_canonical_identity_before_analysis(source, feed, identities, agents, profile_agent):
    original = await seed_profiles(source, feed, identities)
    merged = merge(original)
    original_claim_ids = {claim["id"] for profile in original for claim in profile["claims"]}
    add_meeting(feed, "future", identities[0])
    result = json.loads(await ingest_and_profile({"source": source.name}))

    call = profile_agent[0][-1]
    assert [person["id"] for person in call["participants"]] == [merged["id"]]
    assert {claim["id"] for claim in call["profiles"][0]["claims"]} == original_claim_ids
    updated = profile_db.get_profile(merged["id"])
    assert updated["revision"] > merged["revision"] and len(updated["claims"]) == 3
    assert {claim["id"] for claim in updated["claims"]} > original_claim_ids
    assert result["profiles"]["profile_ids"] == [merged["id"]]
    assert len(agents.analyses) == len(agents.publications) == 3
    assert profile_db.list_profiles(query=source.account_key)["total"] == 1
    assert profile_db.meeting_profiles(meeting_id(source, "initial-0"))["items"][0]["id"] == merged["id"]


@pytest.mark.asyncio
async def test_two_known_alias_speakers_share_one_catalog_entry_and_all_evidence_segments(source, feed, identities, profile_agent):
    merged = merge(await seed_profiles(source, feed, identities))
    add_meeting(feed, "both", *identities)
    await ingest_and_profile({"source": source.name})

    catalog = profile_agent[0][-1]["participants"]
    assert len(catalog) == 1 and catalog[0]["id"] == merged["id"]
    assert catalog[0]["segment_ids"] == ["segment-0", "segment-1"]
    latest = profile_db.get_profile(merged["id"])["claims"][-2:]
    assert {claim["subject_id"] for claim in latest} == {merged["id"]}
    assert {entry["segment_id"] for claim in latest for entry in claim["evidence"]} == {"segment-0", "segment-1"}


@pytest.mark.asyncio
async def test_merge_during_analysis_rebuilds_only_profile_candidate_and_preserves_completed_memories(
    source, feed, identities, agents, profile_agent, monkeypatch,
):
    from services.meetings import profile_analysis
    from services.graphs.library.persona import PersonaProcessingError as MeetingSyncError

    profiles = await seed_profiles(source, feed, identities)
    original = profile_agent[1]

    async def concurrent_merge(*args, **kwargs):
        result = await original(*args, **kwargs)
        merge(profiles)
        return result

    monkeypatch.setattr(profile_analysis, "analyze_profiles", concurrent_merge)
    add_meeting(feed, "interrupted", identities[0])
    with pytest.raises(MeetingSyncError, match="ProfileRevisionConflict"):
        await ingest_and_profile({"source": source.name})
    pending_id = meeting_id(source, "interrupted")
    pending = digestion_db.get_record(pending_id)
    memories = copy.deepcopy(pending["memory_artifact"])
    assert pending["memory_status"] == "done" and pending["profile_artifact"] == {}
    assert len(agents.analyses) == len(agents.publications) == 3

    monkeypatch.setattr(profile_analysis, "analyze_profiles", original)
    profile_due(pending_id)
    await ingest_and_profile({"source": source.name})
    completed = digestion_db.get_record(pending_id)
    assert completed["profile_status"] == "done" and completed["memory_artifact"] == memories
    assert profile_agent[0][-1]["participants"][0]["id"] == profiles[1]["id"]
    assert len(agents.analyses) == len(agents.publications) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("merge_after_resolution", [False, True])
async def test_merge_between_windows_discards_saved_alias_candidate_without_regenerating_memories(
    source, feed, identities, agents, profile_agent, monkeypatch, merge_after_resolution,
):
    from services.meetings import profile_analysis
    from services.graphs.library.persona import PersonaProcessingError as MeetingSyncError

    profiles = await seed_profiles(source, feed, identities)
    original = profile_agent[1]

    async def pause_second(snapshot, window, previous, **kwargs):
        if previous:
            await asyncio.Event().wait()
        return await original(snapshot, window, previous, **kwargs)

    monkeypatch.setattr(enrichment, "WINDOW_SEGMENTS", 1)
    monkeypatch.setattr(enrichment, "AGENT_SECONDS", 0.15)
    monkeypatch.setattr(profile_analysis, "analyze_profiles", pause_second)
    add_meeting(feed, "continued", identities[0], identities[0])
    first = json.loads(await ingest_and_profile({"source": source.name}))
    pending_id = meeting_id(source, "continued")
    pending = digestion_db.get_record(pending_id)
    assert first["profiles"]["outcome"] == "continued" and pending["profile_artifact"]["offset"] == 1
    memories = copy.deepcopy(pending["memory_artifact"])
    memory_calls = len(agents.analyses)
    resolve = profile_db.resolve_participants
    if merge_after_resolution:
        def resolved_then_merge(participants):
            resolved = resolve(participants)
            monkeypatch.setattr(profile_db, "resolve_participants", resolve)
            merge(profiles)
            return resolved
        monkeypatch.setattr(profile_db, "resolve_participants", resolved_then_merge)
    else:
        merge(profiles)

    monkeypatch.setattr(enrichment, "AGENT_SECONDS", 10)
    monkeypatch.setattr(profile_analysis, "analyze_profiles", original)
    with pytest.raises(MeetingSyncError, match="ProfileRevisionConflict"):
        await ingest_and_profile({"source": source.name})
    assert digestion_db.get_record(pending_id)["profile_artifact"] == {}
    monkeypatch.setattr(profile_db, "resolve_participants", resolve)
    profile_due(pending_id)
    await ingest_and_profile({"source": source.name})
    completed = digestion_db.get_record(pending_id)
    assert completed["profile_status"] == "done" and completed["memory_artifact"] == memories
    assert len(agents.analyses) == memory_calls
    assert profile_agent[0][-1]["participants"][0]["id"] == profiles[1]["id"]


@pytest.mark.asyncio
async def test_deleted_canonical_profile_is_not_recreated_by_a_known_alias_in_a_new_meeting(source, feed, identities, profile_agent):
    merged = merge(await seed_profiles(source, feed, identities))
    profile_db.delete_profile(merged["id"], merged["revision"])
    add_meeting(feed, "after-deletion", identities[0])
    result = json.loads(await ingest_and_profile({"source": source.name}))

    call = profile_agent[0][-1]
    assert call["participants"][0]["id"] == merged["id"] and call["profiles"][0]["deleted"]
    assert result["profiles"]["outcome"] == "done" and result["profiles"]["profile_ids"] == []
    assert all(profile_db.get_profile(person["id"]) is None for person in identities)
    assert profile_db.list_profiles(query=source.account_key)["total"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_profile", [False, True])
async def test_manual_attribution_reaches_profile_agent_without_changing_frozen_memory_input(
    source, feed, identities, agents, profile_agent, existing_profile,
):
    if existing_profile:
        await seed_profiles(source, feed, identities)
    target = identities[1] if existing_profile else identities[0]
    add_meeting(feed, "manual", target)
    feed.segments = (TranscriptSegment("I prioritize verified ownership.", {"name": "Me", "source": "microphone"}),)
    await ingest_and_profile({"source": source.name, "digest": False})
    manual_id = meeting_id(source, "manual")
    captured = digestion_db.get_record(manual_id)
    snapshot = copy.deepcopy(captured["snapshot"])
    identity = {"profile_id": target["id"]} if existing_profile else {"email": target["email"]}
    mapping = [{"name": "Alex", **identity, "speaker_key": speaker_key(captured["transcript"]["segments"][0]["speaker"])}]
    management_db.update_participants(manual_id, 0, mapping)
    memory_calls = len(agents.analyses)

    await ingest_and_profile({"source": source.name})
    call = profile_agent[0][-1]
    record = digestion_db.get_record(manual_id)
    assert call["participants"][0]["id"] == target["id"]
    assert call["snapshot"]["manual_participants"] == mapping and call["snapshot"]["participants_revision"] == 1
    assert record["snapshot"] == snapshot and record["profile_artifact"]["participants_revision"] == 1
    assert agents.analyses[-1][0] == snapshot and len(agents.analyses) == memory_calls + 1
    assert profile_db.get_profile(target["id"])["claims"][-1]["evidence"][0]["quote"] == "I prioritize verified ownership."
