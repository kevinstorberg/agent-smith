import copy
import json
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from psycopg2.extras import Json

from scripts.shared.local_postgres import temporary_postgres
from services import config
from services.db import get_connection
from services.db.create import create_database
from services.graphs.runtime import dispatch
from services.meetings import digestion_db, profile_db, profile_directory, profile_metadata, speaker_profiles, stage_db
from services.meetings.analysis import AnalysisBudgetExpired
from services.meetings.outputs import ProfileMetadataPatch
from services.personas import service as persona_service
from services.personas.factory import MeetingContextProvider
from tests.test_meeting_profiles_db import participants as participants
from tests.test_meeting_sync import note, source as source
from tests.test_meeting_transcript_capture import enroll, transcript_page

TEXT = "I work at Example Co as security lead. I started on 2025-01-02 and report to Morgan."


def ready_metadata_meeting(source, external_id="metadata", *, texts=(TEXT,)):
    meeting_id = enroll(source, note(external_id))
    owner = "metadata-capture"
    record = digestion_db.claim_transcript([(source.provider, source.account_key)], owner)
    assert record["meeting_id"] == meeting_id
    try:
        digestion_db.save_capture(meeting_id, owner, digestion_db.get_context(meeting_id), {
            "segments": [transcript_page(text).segments[0].to_dict(index) for index, text in enumerate(texts)],
        }, complete=True)
        # Metadata-only fixtures exercise the historical direct extraction contract.
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE meeting_digestions SET speaker_status='legacy' WHERE meeting_id=%s", (meeting_id,))
    finally:
        digestion_db.release(meeting_id, owner)
    return meeting_id


@pytest.fixture
def metadata_claimed(source):
    meeting_id = ready_metadata_meeting(source)
    owner = "metadata-persona"
    assert digestion_db.claim_profile(source.name, owner)["meeting_id"] == meeting_id
    yield meeting_id, owner, digestion_db.get_record(meeting_id)["transcript_hash"]
    digestion_db.release_profile_owner(owner)


def artifact(participants, *, fields=None, revisions=None):
    return {
        "version": 1, "offset": 1, "items": [], "reason": "Explicit profile facts",
        "expected_revisions": revisions or {person["id"]: 0 for person in participants},
        "metadata_updates": [{"subject_id": participants[0]["id"],
                              "fields": fields or {"company": "Example Co", "job_role": "security lead"},
                              "evidence": [{"segment_id": "segment-0", "quote": TEXT}]}],
    }


def test_metadata_only_output_atomically_populates_canonical_profile(metadata_claimed, participants):
    candidate = artifact(participants)
    original = copy.deepcopy(candidate)
    assert profile_db.apply_profiles(*metadata_claimed, candidate, participants) == [participants[0]["id"]]
    profile = profile_db.get_profile(participants[0]["id"])
    assert profile["metadata"] == {"company": "Example Co", "job_role": "security lead"}
    assert profile["claims"] == [] and profile["revision"] == 1
    assert all(source["meeting_id"] == metadata_claimed[0] and source["transcript_hash"] == metadata_claimed[2]
               and source["evidence"] == candidate["metadata_updates"][0]["evidence"] for source in profile["metadata_provenance"].values())
    assert profile_db.meeting_profiles(metadata_claimed[0])["items"][0]["id"] == profile["id"]
    listed = profile_db.list_profiles(query="Example Co")["items"]
    assert listed[0]["id"] == profile["id"] and listed[0]["meeting_count"] == 1 and listed[0]["claim_count"] == 0
    assert candidate == original


def test_metadata_apply_and_completion_roll_back_together(metadata_claimed, participants, monkeypatch):
    original = stage_db.write_progress

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic receipt failure")

    monkeypatch.setattr(stage_db, "write_progress", interrupted)
    with pytest.raises(RuntimeError, match="Synthetic"):
        profile_db.apply_profiles(*metadata_claimed, artifact(participants), participants)
    assert profile_db.get_profile(participants[0]["id"]) is None
    assert digestion_db.get_record(metadata_claimed[0])["profile_status"] == "pending"


@pytest.mark.parametrize("change", ["withdrawn", "transcript_deleted", "hash_changed", "attribution_changed"])
def test_generated_metadata_visibility_matches_source_on_every_read(metadata_claimed, participants, change):
    profile_db.apply_profiles(*metadata_claimed, artifact(participants), participants)
    before = profile_directory.names(participants[0]["email"])["items"][0]
    assert before["metadata"]["company"] == "Example Co"
    with get_connection() as connection, connection.cursor() as cursor:
        if change == "withdrawn":
            cursor.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (metadata_claimed[0],))
        elif change == "transcript_deleted":
            cursor.execute("UPDATE meeting_digestions SET transcript_status='deleted' WHERE meeting_id=%s", (metadata_claimed[0],))
        elif change == "hash_changed":
            cursor.execute("UPDATE meeting_digestions SET transcript_hash=%s WHERE meeting_id=%s", ("f" * 64, metadata_claimed[0]))
        else:
            cursor.execute("UPDATE meeting_summaries SET participants_revision=participants_revision+1 WHERE id=%s", (metadata_claimed[0],))
    profile = profile_db.get_profile(participants[0]["id"])
    assert profile["metadata"] == profile["metadata_provenance"] == {}
    assert profile_db.load_profiles(participants)[0]["metadata"] == {}
    assert profile_directory.names(participants[0]["email"])["items"][0]["metadata"] == {}
    assert speaker_profiles.read_contexts(participants[0]["email"], None, set())["items"][0]["metadata"] == {}
    assert profile_db.list_profiles(query="Example Co")["total"] == 0
    listed = profile_db.list_profiles(query=participants[0]["email"])["items"]
    assert len(listed) == 1 and listed[0]["metadata"] == {}


def test_human_clear_and_same_value_confirmation_are_protected(metadata_claimed, participants):
    profile_db.apply_profiles(*metadata_claimed, artifact(participants), participants)
    profile = profile_db.update_metadata(participants[0]["id"], 1, metadata={"company": "", "job_role": "security lead"})
    assert profile["revision"] == 2 and profile["metadata"] == {"job_role": "security lead"}
    assert profile["metadata_provenance"] == {"company": {"human": True}, "job_role": {"human": True}}
    same = profile_db.update_metadata(profile["id"], 2, metadata={"company": "", "job_role": "security lead"})
    assert same["revision"] == 2
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (metadata_claimed[0],))
    assert profile_db.get_profile(profile["id"])["metadata"] == {"job_role": "security lead"}


def test_agent_fills_missing_visible_metadata_without_replacing_known_or_human_fields(metadata_claimed, participants, source):
    profile_db.apply_profiles(*metadata_claimed, artifact(participants), participants)
    profile = profile_db.update_metadata(participants[0]["id"], 1, metadata={"company": ""})
    digestion_db.release_profile_owner(metadata_claimed[1])
    meeting_id = ready_metadata_meeting(source, "second-metadata")
    owner = "metadata-second"
    assert digestion_db.claim_profile(source.name, owner)["meeting_id"] == meeting_id
    try:
        record = digestion_db.get_record(meeting_id)
        candidate = artifact(participants, revisions={participants[0]["id"]: profile["revision"], participants[1]["id"]: 0},
                             fields={"company": "Different company", "job_role": "Different role", "supervisor": "Morgan"})
        profile_db.apply_profiles(meeting_id, owner, record["transcript_hash"], candidate, participants)
    finally:
        digestion_db.release_profile_owner(owner)
    final = profile_db.get_profile(profile["id"])
    assert final["metadata"] == {"job_role": "security lead", "supervisor": "Morgan"}
    assert final["metadata_provenance"]["company"] == {"human": True}


def test_metadata_requires_expected_canonical_revision(metadata_claimed, participants):
    with get_connection() as connection, connection.cursor() as cursor:
        person = participants[0]
        cursor.execute("INSERT INTO participant_profiles (id,identity_key,display_name,identity_scope) VALUES (%s,%s,%s,'manual')",
                       (person["id"], person["identity_key"], "A manually identified person"))
    with pytest.raises(profile_db.ProfileRevisionConflict):
        profile_db.apply_profiles(*metadata_claimed, artifact(participants), participants)
    assert profile_db.get_profile(participants[0]["id"])["metadata"] == {}


@pytest.mark.parametrize("changes", [
    {"fields": {"unsupported": "value"}}, {"fields": {"company": " "}},
    {"fields": {"start_date": "2025-13-01"}}, {"fields": {"company": "x" * 4001}},
    {"fields": {}}, {"subject_id": "unknown"},
    {"evidence": [{"segment_id": "segment-1", "quote": TEXT}]},
    {"evidence": [{"segment_id": "segment-0", "quote": "Invented company"}]},
])
def test_metadata_patch_boundary_rejects_invalid_fields_identities_or_evidence(metadata_claimed, participants, changes):
    candidate = artifact(participants)
    candidate["metadata_updates"][0].update(changes)
    with pytest.raises(ValueError):
        profile_db.apply_profiles(*metadata_claimed, candidate, participants)
    assert profile_db.get_profile(participants[0]["id"]) is None


def test_merge_metadata_precedence_preserves_human_clears_and_valid_sources():
    context = {"source": {"available": True, "transcript_status": "ready", "transcript_hash": "hash", "participants_revision": 0}}
    receipt = {"meeting_id": "source", "transcript_hash": "hash", "participants_revision": 0, "evidence": []}
    target = {"metadata": {"job_role": "Old automatic role", "supervisor": "Target supervisor"},
              "metadata_provenance": {"company": {"human": True}, "job_role": receipt, "supervisor": receipt}}
    source = {"metadata": {"company": "Source company", "job_role": "Human source role", "supervisor": "Source supervisor", "other": "Source context"},
              "metadata_provenance": {"company": receipt, "job_role": {"human": True}, "supervisor": receipt, "other": receipt}}
    original = copy.deepcopy((source, target))
    metadata, provenance = profile_metadata.merge(source, target, context)
    assert metadata == {"job_role": "Human source role", "supervisor": "Target supervisor", "other": "Source context"}
    assert provenance["company"] == provenance["job_role"] == {"human": True}
    assert (source, target) == original


def test_metadata_migration_preserves_existing_human_values_and_completed_receipts(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "f8a0b1c2d3e4")
        profile_id = str(uuid4())
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO participant_profiles (id,identity_key,display_name,identity_scope,metadata)
                VALUES (%s,%s,'Synthetic person','manual',%s)""", (profile_id, "manual:" + profile_id, Json({"company": "Human company"})))
        for index in range(2):
            command.upgrade(migration, "head")
            with psycopg2.connect(url) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT metadata,metadata_provenance FROM participant_profiles WHERE id=%s", (profile_id,))
                assert cursor.fetchone() == ({"company": "Human company"}, {"company": {"human": True}})
            if index == 0:
                command.downgrade(migration, "f8a0b1c2d3e4")


def test_typed_patch_normalizes_supported_metadata_without_dropping_values():
    patch = ProfileMetadataPatch(subject_id="person", fields={"company": " Example Co ", "start_date": "2025-01-02"},
                                 evidence=[{"segment_id": "segment-0", "quote": TEXT}])
    assert patch.fields == {"company": "Example Co", "start_date": "2025-01-02"}


def test_profile_merge_preserves_human_clear_and_selected_survivor(metadata_claimed, participants):
    profile_db.apply_profiles(*metadata_claimed, artifact(participants), participants)
    target = profile_db.get_profile(participants[0]["id"])
    source = profile_db.create_profile("Synthetic human-edited profile")
    try:
        source = profile_db.update_metadata(source["id"], source["revision"], metadata={"company": "", "job_role": "Human-reviewed role"})
        merged = profile_db.merge_profiles(source["id"], target["id"], source["revision"], target["revision"])
        assert merged["id"] == target["id"] and merged["metadata"] == {"job_role": "Human-reviewed role"}
        assert merged["metadata_provenance"] == {"company": {"human": True}, "job_role": {"human": True}}
        assert merged["merge_history"][-1]["previous_target"]["metadata"]["company"] == "Example Co"
        assert merged["merge_history"][-1]["previous_target"]["metadata_provenance"]["company"]["meeting_id"] == metadata_claimed[0]
        assert profile_db.get_profile(source["id"])["id"] == target["id"]
    finally:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (source["id"],))


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_metadata_checkpoints_resume_without_reviewing_old_windows_or_completed_contexts(source, monkeypatch, legacy):
    from services.meetings import profile_analysis

    meeting_id = ready_metadata_meeting(source, texts=(TEXT, "I report to Morgan."))
    monkeypatch.setattr(persona_service, "WINDOW_SEGMENTS", 1)
    provider = MeetingContextProvider()
    record = provider.get_record(meeting_id)
    _, participants, profiles = provider.prepare_context(record)
    catalog_ids = [person["id"] for person in participants]
    attempts, earlier = [], []
    interrupted = False
    if legacy:
        candidate = {"version": 1, "offset": 1, "items": [], "reason": "Old reviewed window",
                     "model": "synthetic", "expected_revisions": {person["id"]: person["revision"] for person in profiles}}
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE meeting_digestions SET profile_artifact=%s WHERE meeting_id=%s", (Json(candidate), meeting_id))

    async def analyze(snapshot, window, previous, *, participants, profiles, memories, deadline, previous_metadata):
        nonlocal interrupted
        index = int(window[0]["id"].removeprefix("segment-"))
        if not legacy and index == 1 and not interrupted:
            interrupted = True
            raise AnalysisBudgetExpired("Synthetic checkpoint boundary")
        attempts.append(index)
        earlier.append(copy.deepcopy(previous_metadata))
        fields = {"company": "Example Co"} if index == 0 else {"supervisor": "Morgan"}
        return {"items": [], "metadata_updates": [{"subject_id": participants[0]["id"], "fields": fields,
                                                     "evidence": [{"segment_id": window[0]["id"], "quote": window[0]["text"]}]}], "reason": ""}

    monkeypatch.setattr(profile_analysis, "analyze_profiles", analyze)
    try:
        if not legacy:
            first = json.loads(await dispatch("persona", {"source": source.name}))["profiles"]
            assert first["outcome"] == "continued" and first["progress"]["processed_units"] == first["progress"]["staged_count"] == 1
            assert profile_db.get_profile(participants[0]["id"]) is None
        result = json.loads(await dispatch("persona", {"source": source.name}))["profiles"]
        assert result["outcome"] == "done" and result["profile_ids"] == [participants[0]["id"]]
        assert attempts == ([1] if legacy else [0, 1])
        assert bool(earlier[-1]) is (not legacy)
        expected = {"supervisor": "Morgan"} | ({} if legacy else {"company": "Example Co"})
        assert profile_db.get_profile(participants[0]["id"])["metadata"] == expected
        assert json.loads(await dispatch("persona", {"source": source.name}))["profiles"]["outcome"] == "idle"
        assert attempts == ([1] if legacy else [0, 1])
    finally:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE id IN %s", (tuple(catalog_ids),))


def test_new_evidence_can_fill_a_field_whose_previous_generated_source_is_unavailable(metadata_claimed, participants, source):
    profile_db.apply_profiles(*metadata_claimed, artifact(participants), participants)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (metadata_claimed[0],))
    assert profile_db.get_profile(participants[0]["id"])["metadata"] == {}
    digestion_db.release_profile_owner(metadata_claimed[1])
    meeting_id = ready_metadata_meeting(source, "replacement-metadata")
    owner = "metadata-replacement"
    assert digestion_db.claim_profile(source.name, owner)["meeting_id"] == meeting_id
    try:
        record = digestion_db.get_record(meeting_id)
        candidate = artifact(participants, fields={"company": "Example Co"},
                             revisions={participants[0]["id"]: 1, participants[1]["id"]: 0})
        assert profile_db.apply_profiles(meeting_id, owner, record["transcript_hash"], candidate, participants) == [participants[0]["id"]]
    finally:
        digestion_db.release_profile_owner(owner)
    profile = profile_db.get_profile(participants[0]["id"])
    assert profile["metadata"] == {"company": "Example Co"}
    assert profile["metadata_provenance"]["company"]["meeting_id"] == meeting_id
    assert "job_role" not in profile["metadata_provenance"]


def test_source_withdrawal_hides_generated_metadata_from_public_merge_history_but_retains_raw_audit(metadata_claimed, participants):
    profile_db.apply_profiles(*metadata_claimed, artifact(participants), participants)
    generated = profile_db.get_profile(participants[0]["id"])
    human = profile_db.create_profile("Synthetic human survivor")
    try:
        human = profile_db.update_metadata(human["id"], human["revision"], metadata={"company": "Human company", "job_role": "Human role"})
        profile_db.merge_profiles(generated["id"], human["id"], generated["revision"], human["revision"])
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE meeting_summaries SET available=false WHERE id=%s", (metadata_claimed[0],))
            cursor.execute("SELECT merge_history FROM participant_profiles WHERE id=%s", (human["id"],))
            raw = cursor.fetchone()[0]
        assert "Example Co" in json.dumps(raw)
        public = profile_db.get_profile(human["id"])
        assert public["metadata"] == {"company": "Human company", "job_role": "Human role"}
        assert "Example Co" not in json.dumps(public) and TEXT not in json.dumps(public)
        resolved = profile_db.resolve_participants(participants[:1])
        loaded = profile_db.load_profiles(resolved)
        assert "Example Co" not in json.dumps(loaded) and TEXT not in json.dumps(loaded)
        assert loaded[0]["merge_history"][-1]["previous_source"]["metadata"] == {}
    finally:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM participant_profiles WHERE merged_into=%s", (human["id"],))
            cursor.execute("DELETE FROM participant_profiles WHERE id=%s", (human["id"],))


def test_metadata_downgrade_does_not_reclassify_generated_facts_as_human(monkeypatch):
    with temporary_postgres() as url:
        create_database(url)
        monkeypatch.setattr(config, "DATABASE_URL", url)
        migration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(migration, "head")
        profile_id = str(uuid4())
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            generated = {"meeting_id": str(uuid4()), "transcript_hash": "h" * 64,
                         "participants_revision": 0, "evidence": [{"quote": "Private historical source quote"}]}
            history = [{"action": "merge", "previous_source": {
                "metadata": {"company": "Private historical company", "other": "Legacy historical value"},
                "metadata_provenance": {"company": generated}}, "previous_target": {
                    "metadata": {"company": "Human historical company"}, "metadata_provenance": {"company": {"human": True}}}}]
            cursor.execute("""INSERT INTO participant_profiles
                (id,identity_key,display_name,identity_scope,metadata,metadata_provenance,merge_history)
                VALUES (%s,%s,'Synthetic person','manual',%s,%s,%s)""", (
                    profile_id, "manual:" + profile_id,
                    Json({"company": "Human company", "job_role": "Private generated role", "other": "Untracked legacy value"}),
                    Json({"company": {"human": True}, "job_role": generated}), Json(history)))
        command.downgrade(migration, "f8a0b1c2d3e4")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT metadata,merge_history FROM participant_profiles WHERE id=%s", (profile_id,))
            metadata, downgraded_history = cursor.fetchone()
            assert metadata == {"company": "Human company", "other": "Untracked legacy value"}
            assert "Private" not in json.dumps((metadata, downgraded_history))
            assert downgraded_history[0]["previous_source"]["metadata"] == {"other": "Legacy historical value"}
            assert downgraded_history[0]["previous_target"] == history[0]["previous_target"]
        command.upgrade(migration, "head")
        with psycopg2.connect(url) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT metadata,metadata_provenance FROM participant_profiles WHERE id=%s", (profile_id,))
            metadata, provenance = cursor.fetchone()
            assert metadata == {"company": "Human company", "other": "Untracked legacy value"}
            assert provenance == {"company": {"human": True}, "other": {"human": True}}
            assert "Private generated role" not in json.dumps((metadata, provenance))
