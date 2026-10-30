import asyncio
import copy
import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from services.graphs import agents
from services.db import get_connection
from services.meetings import digestion_db, management_db, profile_db, speaker_analysis, speaker_context, speaker_db
from tests.test_meeting_memory_agent import ScriptedModel, call
from tests.test_meeting_memory_flow import feed as feed, ready as ready
from tests.test_meeting_sync import source as source


class SpeakerModel(ScriptedModel):
    definitions: list[dict] = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.definitions = [convert_to_openai_tool(tool) for tool in tools]
        return super().bind_tools(tools, **kwargs)


@pytest.fixture
def speaker_model(monkeypatch):
    def install(replies):
        instance = SpeakerModel(replies=replies)
        monkeypatch.setattr(agents, "build_chat_model", lambda *args, **kwargs: instance)
        return instance
    return install


def request_data(messages):
    return json.loads(next(message.content for message in messages if isinstance(message, HumanMessage)).split("\n", 1)[1])


def statement(text="The roadmap needs a security review.", name=None, index=0):
    return {"id": f"segment-{index}", "text": text, "speaker": {"name": name} if name else {"attribution": "them"}}


def assignment(segment, name, **fields):
    return {"segment_id": segment["id"], "name": name, "confidence": "high", "rationale": "Explicit supplied identity",
            "evidence": [{"segment_id": segment["id"], "quote": segment["text"]}], **fields}


def test_provider_named_statement_is_a_supplied_identity_without_a_self_introduction():
    target = statement(name="Alex Taylor")
    known = speaker_analysis.candidates({"metadata": {}}, [target])
    result = speaker_analysis.validate_assignments([assignment(target, "Alex Taylor")], [target], [], known, [])
    assert result[0]["name"] == "Alex Taylor"


def test_linked_email_keeps_roster_alias_on_the_same_canonical_identity():
    profile_id = str(uuid4())
    known = speaker_analysis.candidates({"manual_participants": [{"name": "Alex J. Taylor", "email": "PERSONAL@example.test"}],
        "identity_candidates": [{"name": "Alex Taylor", "email": "personal@example.test", "profile_id": profile_id},
                                {"name": "Alex Taylor", "email": "work@example.test", "profile_id": profile_id}]})
    target = statement()
    result = speaker_analysis.validate_assignments([
        assignment(target, "Alex J. Taylor", email="PERSONAL@example.test", profile_id=profile_id),
    ], [target], [], known, [])
    assert result[0]["email"] == "personal@example.test" and result[0]["profile_id"] == profile_id


@pytest.mark.parametrize("identity", ["conflicting_email", "conflicting_profile", "homonym"])
def test_identity_context_never_merges_unrelated_names(identity):
    first, second = str(uuid4()), str(uuid4())
    known = [{"name": "Alex", "email": "first@example.test", "profile_id": first},
             {"name": "Alex", "email": "second@example.test", "profile_id": second}]
    fields = {"email": "second@example.test", "profile_id": first} if identity == "conflicting_email" else (
        {"profile_id": str(uuid4())} if identity == "conflicting_profile" else {})
    target = statement()
    with pytest.raises(ValueError):
        speaker_analysis.validate_assignments([assignment(target, "Alex", **fields)], [target], [], known, [])


def test_multibyte_targets_are_split_as_complete_statements():
    segments = [statement("🙂" * 1500, index=index) for index in range(5)]
    targets, end = speaker_analysis.target_window(segments, 0)
    assert 0 < end < len(segments)
    assert all(row["text"] == "🙂" * 1500 for row in targets)
    assert len(json.dumps(targets, ensure_ascii=False).encode()) <= 16_000


def test_complete_context_pack_retains_opening_human_quotes_and_limits_multibyte_entries():
    profile_id = str(uuid4())
    segments = [statement("🙂" * 500, index=index) for index in range(50)]
    segments[0]["text"] = "I'm Lex, and I'll explain the security review."
    segments[9]["text"] = "Our threat model needs a review."
    snapshot = {"id": str(uuid4()), "title": "Security", "summary_text": "Security review and roadmap.",
                "manual_participants": [{"name": "Alex", "profile_id": profile_id, "segment_id": "segment-9"}],
                "identity_candidates": [{"name": "Alex", "profile_id": profile_id, "nicknames": ["Lex"],
                                         "metadata": {"company": "Example", "job_role": "CTO", "supervisor": "Blair"}}]}
    context, anchors = speaker_context.window_context(snapshot, segments, 40, [])
    data = speaker_context.quoted_context(snapshot, segments[40:42], context, anchors)
    assert speaker_context.encoded_size(data) <= 32_000
    assert any(row["id"] == "segment-0" and row["text"] == segments[0]["text"] for row in data["read_only_context"])
    assert data["read_only_identity_anchors"][0] == {
        "name": "Alex", "profile_id": profile_id, "segment_id": "segment-9", "text": segments[9]["text"], "source": "human", "confidence": "high",
    }
    assert data["meeting"]["summary_excerpt"] == snapshot["summary_text"]
    assert data["candidates"][0]["metadata"]["supervisor"] == "Blair"
    assert data["omitted"]["read_only_context"] > 0
    for supplied in data["read_only_context"]:
        assert supplied["text"] == segments[int(supplied["id"].split("-")[1])]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("multibyte", [False, True])
async def test_later_actual_model_request_receives_bootstrap_manual_anchor_and_metadata(speaker_model, multibyte):
    segments = [statement("🙂" * 500 if multibyte else f"Statement {index}.", index=index) for index in range(42)]
    segments[0]["text"] = "I'm Lex, and I'll review security."
    segments[9]["text"] = "I own the roadmap."
    person = str(uuid4())
    snapshot = {"id": str(uuid4()), "summary_text": "Product security planning", "metadata": {"owner": {"name": "Blair", "email": "BLAIR@example.test"}},
                "manual_participants": [{"name": "Alex", "profile_id": person, "segment_id": "segment-9"}],
                "identity_candidates": [{"name": "Alex", "aliases": ["Alex J. Taylor"], "nicknames": ["Lex"], "profile_id": person,
                                         "revision": 3, "metadata": {"company": "Example", "job_role": "Lead", "supervisor": "Blair"}}]}
    context, anchors = speaker_context.window_context(snapshot, segments, 40, [])
    item = assignment(segments[40], "Lex", profile_id=person)
    item["evidence"] = [{"segment_id": "segment-0", "quote": segments[0]["text"]}]
    instance = speaker_model([call("stage_speakers", assignments=[item], reason="One target remains ambiguous"), AIMessage(content="Done")])
    result = await speaker_analysis.identify_statements(snapshot, segments[40:], context=context, anchors=anchors,
                                                       deadline=asyncio.get_running_loop().time() + 20)
    data = request_data(instance.seen[0])
    assert result["assignments"][0]["segment_id"] == "segment-40" and len(result["assignments"]) == 1
    assert data["read_only_identity_anchors"][0]["source"] == "human"
    assert data["meeting"]["owner"] == {"name": "Blair", "email": "blair@example.test"}
    candidate = next(row for row in data["candidates"] if row.get("profile_id") == person)
    assert candidate["metadata"] == snapshot["identity_candidates"][0]["metadata"]
    assert "Alex J. Taylor" in candidate["aliases"] and "Lex" in candidate["aliases"]
    assert result["profile_revisions"] == {person: 3}
    for messages in instance.seen:
        assert speaker_context.encoded_size({"messages": [message.model_dump() for message in messages], "tools": instance.definitions}) <= 48_000
    # Shared audio identity does not assign neighboring statements automatically.
    from services.meetings.participants import meeting_participants
    people = meeting_participants({**snapshot, "statement_attributions": result["assignments"]}, segments)
    assert {key for row in people for key in row["segment_ids"]} == {"segment-9", "segment-40"}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["missing", "rejected", "schema", "malformed"])
async def test_speaker_stage_diagnostics_are_safe_and_do_not_add_calls(case, speaker_model, caplog):
    private = "PRIVATE_TRANSCRIPT_AND_MODEL_TEXT"
    target = statement(private)
    replies = [AIMessage(content=private, response_metadata={"finish_reason": private})]
    if case == "rejected":
        invalid = assignment(target, "Unknown")
        invalid["evidence"][0]["quote"] = "Invented"
        replies.insert(0, call("stage_speakers", assignments=[invalid]))
    elif case == "schema":
        replies.insert(0, call("stage_speakers", assignments="not a list"))
    elif case == "malformed":
        replies[0] = AIMessage(content=private, invalid_tool_calls=[{"name": "stage_speakers", "args": private, "id": "bad", "error": private}])
    instance = speaker_model(copy.deepcopy(replies))
    with pytest.raises(speaker_analysis.SpeakerAnalysisError) as caught:
        await speaker_analysis.identify_statements({"id": str(uuid4())}, [target], context=[], anchors=[], deadline=asyncio.get_running_loop().time() + 20)
    assert caught.value.error_type == ("SpeakerStageMissing" if case == "missing" else "SpeakerStageRejected")
    assert len(instance.seen) == len(replies) <= 3
    assert private not in str(caught.value) + caplog.text
    assert "model_calls" in caplog.text and "invalid_tool_calls" in caplog.text


@pytest.mark.asyncio
async def test_valid_empty_speaker_stage_is_success_and_has_no_hidden_retry(speaker_model):
    instance = speaker_model([call("stage_speakers", assignments=[], reason="Shared voices remain ambiguous"), AIMessage(content="Done")])
    result = await speaker_analysis.identify_statements({"id": str(uuid4())}, [statement()], context=[], anchors=[], deadline=asyncio.get_running_loop().time() + 20)
    assert result == {"assignments": [], "reason": "Shared voices remain ambiguous"}
    assert len(instance.seen) == 2


@pytest.mark.asyncio
async def test_rejected_stage_can_be_repaired_within_three_existing_model_turns(speaker_model):
    instance = speaker_model([call("stage_speakers", assignments=[], reason=""),
                              call("stage_speakers", assignments=[], reason="Several voices remain uncertain"), AIMessage(content="Done")])
    result = await speaker_analysis.identify_statements({"id": str(uuid4())}, [statement()], context=[], anchors=[], deadline=asyncio.get_running_loop().time() + 20)
    assert result["assignments"] == [] and len(instance.seen) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["model", "tools"])
async def test_speaker_retains_existing_three_model_and_four_tool_limits(speaker_model, limit):
    unknown = str(uuid4())
    if limit == "model":
        replies = [call("search_known_profiles", profile_id=unknown) for _ in range(4)]
    else:
        replies = [AIMessage(content="", tool_calls=[{"name": "search_known_profiles", "args": {"profile_id": unknown},
                                                     "id": f"lookup-{index}", "type": "tool_call"} for index in range(5)])]
    instance = speaker_model(replies)
    with pytest.raises(speaker_analysis.SpeakerAnalysisError) as caught:
        await speaker_analysis.identify_statements({"id": str(uuid4())}, [statement()], context=[], anchors=[], deadline=asyncio.get_running_loop().time() + 20)
    assert caught.value.error_type == ("ModelCallLimitExceededError" if limit == "model" else "ToolCallLimitExceededError")
    assert len(instance.seen) <= 3


@pytest.mark.asyncio
async def test_accumulated_model_and_lookup_history_is_bounded_before_next_call(speaker_model, monkeypatch):
    from services.meetings import speaker_profiles

    monkeypatch.setattr(speaker_profiles, "read_contexts", lambda *args: {"items": [], "matched": 0, "omitted": 0})
    first = call("search_known_profiles", query="Alex")
    first.content = "PRIVATE_LONG_RESPONSE" * 3000
    instance = speaker_model([first, AIMessage(content="Must not execute")])
    with pytest.raises(speaker_analysis.SpeakerAnalysisError) as caught:
        await speaker_analysis.identify_statements({"id": str(uuid4())}, [statement()], context=[], anchors=[], deadline=asyncio.get_running_loop().time() + 20)
    assert caught.value.error_type == "SpeakerRequestTooLarge" and len(instance.seen) == 1


def test_same_canonical_context_rejects_conflicting_revisions():
    profile_id = str(uuid4())
    with pytest.raises(ValueError, match="Conflicting revisions"):
        speaker_context.identities([{"name": "Alex", "profile_id": profile_id, "revision": 3},
                                    {"name": "Alex", "profile_id": profile_id, "revision": 4}])


@pytest.mark.asyncio
async def test_identity_conflict_is_not_reported_as_a_byte_budget_failure(speaker_model):
    profile_id = str(uuid4())
    instance = speaker_model([AIMessage(content="Must not execute")])
    with pytest.raises(speaker_context.SpeakerIdentityConflict):
        await speaker_analysis.identify_statements({"id": str(uuid4()), "identity_candidates": [
            {"name": "Alex", "profile_id": profile_id, "revision": 3}, {"name": "Alex", "profile_id": profile_id, "revision": 4},
        ]}, [statement()], context=[], anchors=[], deadline=asyncio.get_running_loop().time() + 20)
    assert instance.seen == []


@pytest.mark.asyncio
async def test_profile_lookup_cannot_replace_the_initial_revision_fence(speaker_model, monkeypatch):
    from services.meetings import speaker_profiles

    profile_id = str(uuid4())
    monkeypatch.setattr(speaker_profiles, "read_contexts", lambda *args: {"items": [{"name": "Alex", "profile_id": profile_id, "revision": 4}], "matched": 1})
    instance = speaker_model([call("search_known_profiles", profile_id=profile_id), AIMessage(content="Must not run")])
    with pytest.raises(speaker_db.AttributionInputChanged):
        await speaker_analysis.identify_statements({"id": str(uuid4()), "identity_candidates": [{"name": "Alex", "profile_id": profile_id, "revision": 3}]},
                                                   [statement()], context=[], anchors=[], deadline=asyncio.get_running_loop().time() + 20)
    assert len(instance.seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["meeting", "participants", "profile", "hash"])
async def test_native_source_and_human_profile_edits_stop_the_next_model_turn(ready, source, speaker_model, change):
    person = profile_db.create_profile("Speaker fence " + uuid4().hex)
    owner = "speaker-fence"
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_digestions SET speaker_status='pending' WHERE meeting_id=%s", (ready,))
    claimed = digestion_db.claim_identification(source.name, owner)
    record, artifact = speaker_db.prepare(ready, owner, claimed["transcript_hash"])
    snapshot = speaker_db.context_snapshot(record, manual=artifact["manual_snapshot"])
    # A manually supplied ID outside a bounded metadata seed still receives a revision fence.
    snapshot["identity_candidates"] = [{"name": person["display_name"], "profile_id": person["id"]}]
    checks = 0

    async def validate(expected):
        nonlocal checks
        checks += 1
        if checks == 2:
            if change == "profile":
                profile_db.update_metadata(person["id"], person["revision"], metadata={"company": "Human edit"})
            else:
                with get_connection() as connection, connection.cursor() as cursor:
                    if change == "meeting":
                        cursor.execute("UPDATE meeting_summaries SET revision=revision+1 WHERE id=%s", (ready,))
                    elif change == "participants":
                        cursor.execute("UPDATE meeting_summaries SET participants_revision=participants_revision+1 WHERE id=%s", (ready,))
                    else:
                        cursor.execute("UPDATE meeting_digestions SET transcript_hash=%s WHERE meeting_id=%s", ("f" * 64, ready))
        return speaker_db.validate_context(ready, owner, claimed["transcript_hash"], artifact, expected)

    instance = speaker_model([call("stage_speakers", assignments=[], reason="Uncertain"), AIMessage(content="Must not run")])
    try:
        with pytest.raises(speaker_analysis.SpeakerAnalysisError if change == "hash" else speaker_db.AttributionInputChanged):
            await speaker_analysis.identify_statements(snapshot, record["transcript"]["segments"], context=[], anchors=[],
                                                       validate_context=validate, deadline=asyncio.get_running_loop().time() + 20)
        assert len(instance.seen) == 1 and checks == 2
        assert speaker_db.committed(digestion_db.get_record(ready)) == []
    finally:
        digestion_db.release(ready, owner)
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (person["id"],))


def test_native_speaker_preparation_uses_live_summary_and_rebuilds_changed_profile_checkpoint(ready, source):
    person = profile_db.create_profile("Speaker resume " + uuid4().hex)
    owner = "speaker-resume"
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_digestions SET speaker_status='pending' WHERE meeting_id=%s", (ready,))
        cursor.execute("UPDATE meeting_summaries SET title='Live title',summary_text='Live summary',revision=revision+1 WHERE id=%s", (ready,))
    claimed = digestion_db.claim_identification(source.name, owner)
    record, artifact = speaker_db.prepare(ready, owner, claimed["transcript_hash"])
    assert record["snapshot"]["title"] == "Live title" and record["snapshot"]["summary_text"] == "Live summary"
    artifact.update(offset=1, profile_revisions={person["id"]: person["revision"]})
    speaker_db.save_progress(ready, owner, claimed["transcript_hash"], artifact)
    try:
        profile_db.update_metadata(person["id"], person["revision"], metadata={"company": "Updated before resume"})
        _, refreshed = speaker_db.prepare(ready, owner, claimed["transcript_hash"])
        assert refreshed["offset"] == 0 and refreshed["profile_revisions"] == {}
        with pytest.raises(speaker_db.AttributionInputChanged):
            speaker_db.validate_context(ready, owner, claimed["transcript_hash"], artifact, {person["id"]: None})
        with pytest.raises(speaker_db.AttributionInputChanged):
            speaker_db.apply(ready, owner, claimed["transcript_hash"], artifact)
    finally:
        digestion_db.release(ready, owner)
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (person["id"],))


def test_merged_manual_profile_is_canonicalized_only_in_readonly_speaker_context(ready, source):
    target = profile_db.create_profile("Canonical person " + uuid4().hex)
    alias = profile_db.create_profile("Former spelling " + uuid4().hex)
    row = digestion_db.get_record(ready)
    management_db.update_participants(ready, 0, [{"name": alias["display_name"], "profile_id": alias["id"], "segment_id": "segment-0"}], row["transcript_hash"])
    profile_db.merge_profiles(alias["id"], target["id"], alias["revision"], target["revision"])
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_digestions SET speaker_status='pending' WHERE meeting_id=%s", (ready,))
    claimed = digestion_db.claim_identification(source.name, "merged-context")
    try:
        current, artifact = speaker_db.prepare(ready, "merged-context", claimed["transcript_hash"])
        assert artifact["manual_snapshot"][0]["profile_id"] == alias["id"]
        assert current["manual_context"][0]["profile_id"] == target["id"]
        canonical = profile_db.get_profile(target["id"])
        assert speaker_db.validate_context(ready, "merged-context", claimed["transcript_hash"], artifact, {target["id"]: None}) == {target["id"]: canonical["revision"]}
        assert management_db.get_participants(ready)["items"][0]["profile_id"] == alias["id"]
    finally:
        digestion_db.release(ready, "merged-context")
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id IN %s", ((alias["id"], target["id"]),))
