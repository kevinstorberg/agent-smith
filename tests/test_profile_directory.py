import copy
import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from services.db import get_connection
from services.meetings import profile_analysis, profile_db, profile_directory
from tests.test_meeting_memory_agent import backend as backend, call, model as model
from tests.test_meeting_profiles_db import claimed as claimed, participants as participants, candidate
from tests.test_meeting_sync import source as source


@pytest.fixture
def people():
    suffix = uuid4().hex
    rows = [profile_db.create_profile(f"{name} {suffix}", f"{name}-{suffix}@example.test") for name in ("Alex", "Blair", "Casey")]
    try:
        yield rows
    finally:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id IN %s OR merged_into IN %s",
                           (tuple(row["id"] for row in rows), tuple(row["id"] for row in rows)))


def test_directory_searches_canonical_names_nicknames_and_alias_emails(people):
    alex, blair, casey = people
    alex = profile_db.update_metadata(alex["id"], alex["revision"], nicknames=["UniqueLex" + alex["id"]])
    profile_db.merge_profiles(blair["id"], alex["id"], blair["revision"], alex["revision"])
    for query in ("UniqueLex" + alex["id"], blair["display_name"], blair["email"].upper()):
        page = profile_directory.names(query)
        assert [row["id"] for row in page["items"]] == [alex["id"]]
        assert sorted(page["items"][0]["emails"]) == sorted([alex["email"], blair["email"]])
    profile_db.delete_profile(casey["id"], casey["revision"])
    assert profile_directory.names(casey["email"])["total"] == 0


def test_directory_envelope_reports_omissions_and_pages_without_skips(people, monkeypatch):
    query = people[0]["display_name"].split()[-1]
    monkeypatch.setattr(profile_directory, "DIRECTORY_CHARS", 500)
    offset, ids = 0, []
    while offset is not None:
        page = profile_directory.names(query, offset=offset, limit=100)
        ids.extend(row["id"] for row in page["items"])
        offset = page["next_offset"]
        assert len(json.dumps(page, ensure_ascii=False)) <= 500
    assert set(ids) == {row["id"] for row in people} and len(ids) == 3


@pytest.mark.asyncio
async def test_true_react_discovers_reads_and_checkpoints_only_referenced_targets(people, backend, model):
    alex, blair, casey = people
    participant = {**profile_directory.participant(alex), "segment_ids": ["segment-0"]}
    text = "I rely on Blair for a careful security review."
    claim = {"subject_id": alex["id"], "target_id": blair["id"], "category": "perception",
             "epistemic": "self_report", "confidence": "medium", "content": text, "rationale": "Explicit statement",
             "evidence": [{"segment_id": "segment-0", "quote": text}]}
    instance, _ = model([
        call("list_profile_names", query=blair["email"]), call("get_profile", profile_id=blair["id"]),
        call("list_profile_names", query=casey["email"]), call("get_profile", profile_id=casey["id"]),
        call("stage_profiles", items=[claim]), AIMessage(content="Done"),
    ])
    result = await profile_analysis.analyze_profiles(
        {"id": str(uuid4())}, [{"id": "segment-0", "text": text}], [],
        participants=[participant], profiles=[alex], memories=[],
    )
    data = json.loads(next(message.content for message in instance.seen[0] if isinstance(message, HumanMessage)).split("\n", 1)[1])
    assert {row["id"] for row in data["known_profile_directory"]["items"]} >= {row["id"] for row in people}
    assert [row["id"] for row in result["directory_participants"]] == [blair["id"]]
    assert result["directory_participants"][0]["segment_ids"] == []
    artifact = {"expected_revisions": {alex["id"]: alex["revision"]}}
    extended = profile_directory.checkpoint_targets(artifact, [participant], result)
    assert artifact["expected_revisions"] == {alex["id"]: alex["revision"], blair["id"]: blair["revision"]}
    assert profile_directory.extend_catalog([participant], artifact) == extended
    assert casey["id"] not in artifact["expected_revisions"]


@pytest.mark.asyncio
async def test_directory_only_people_cannot_become_subjects_or_receive_metadata(people):
    alex, blair, _ = people
    participant = {**profile_directory.participant(alex), "segment_ids": ["segment-0"]}
    context = profile_analysis.AnalysisContext({}, [{"id": "segment-0", "text": "I value security."}], [], require_memory_search=False)
    tools = {item.name: item for item in profile_analysis._profile_tools(
        context, {alex["id"]: participant}, [alex], directory={"items": [{"id": blair["id"]}]},
    )}
    await tools["get_profile"].ainvoke({"profile_id": blair["id"]})
    result = await tools["stage_profiles"].ainvoke({"items": [], "metadata_updates": [
        {"subject_id": blair["id"], "fields": {"company": "Invented"}, "evidence": [{"segment_id": "segment-0", "quote": "I value security."}]},
    ]})
    assert "directory-only" in result and context.collector == {}


def test_directory_checkpoint_rejects_replacing_mapped_speakers(people):
    identity = {**profile_directory.participant(people[0]), "segment_ids": ["segment-0"]}
    artifact = {"directory_participants": [profile_directory.participant(people[0])]}
    before = copy.deepcopy(artifact)
    with pytest.raises(ValueError, match="cannot replace"):
        profile_directory.extend_catalog([identity], artifact)
    assert artifact == before


@pytest.mark.parametrize("changed_target", [False, True])
def test_only_referenced_directory_revision_fences_atomic_profile_apply(people, claimed, participants, changed_target):
    _, target, unrelated = people
    artifact = candidate(participants)
    artifact["items"][0]["target_id"] = target["id"]
    extended = profile_directory.checkpoint_targets(artifact, participants, {
        "directory_participants": [{**profile_directory.participant(target), "revision": target["revision"]}],
    })
    edited = target if changed_target else unrelated
    profile_db.update_metadata(edited["id"], edited["revision"], tags=["human-edit"])
    if changed_target:
        with pytest.raises(profile_db.ProfileRevisionConflict, match="changed"):
            profile_db.apply_profiles(*claimed, artifact, extended)
        assert profile_db.get_profile(participants[0]["id"]) is None
    else:
        ids = profile_db.apply_profiles(*claimed, artifact, extended)
        assert participants[0]["id"] in ids
        profile = profile_db.get_profile(participants[0]["id"])
        assert profile["claims"][0]["target_id"] == target["id"]
