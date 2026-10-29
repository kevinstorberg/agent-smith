import copy
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from services.db import get_connection
from services.meetings import db, digestion_db, memory_db, profile_db, stage_db
from tests.test_meeting_sync import note, source as source
from tests.test_meeting_transcript_capture import enroll, transcript_page


@pytest.fixture
def participants():
    suffix = uuid4().hex
    result = [{
        "id": str(uuid4()), "identity_key": f"email:{name}-{suffix}@example.test", "display_name": name,
        "email": f"{name}-{suffix}@example.test", "identity_scope": "email", "segment_ids": [f"segment-{index}"],
    } for index, name in enumerate(("Alex", "Blair"))]
    yield result
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM participant_profiles WHERE id IN %s", (tuple(item["id"] for item in result),))


def ready_meeting(source, external_id="one"):
    meeting_id = enroll(source, note(external_id))
    owner = "profile-test-capture"
    assert digestion_db.claim_transcript([(source.provider, source.account_key)], owner)["meeting_id"] == meeting_id
    digestion_db.save_capture(meeting_id, owner, digestion_db.get_context(meeting_id), {
        "segments": [transcript_page(text).segments[0].to_dict(index)
                     for index, text in enumerate(("I prioritize reliability", "I value direct communication"))],
    }, complete=True)
    record = digestion_db.get_record(meeting_id)
    memory_db.save_progress(meeting_id, owner, record["transcript_hash"], {"items": [], "reason": "No novel memory"}, complete=True)
    digestion_db.release(meeting_id, owner)
    return meeting_id


@pytest.fixture
def claimed(source):
    meeting_id = ready_meeting(source)
    owner = "profile-test-owner"
    assert digestion_db.claim_digestion([(source.provider, source.account_key)], owner)["meeting_id"] == meeting_id
    yield meeting_id, owner, digestion_db.get_record(meeting_id)["transcript_hash"]
    digestion_db.release(meeting_id, owner)


def candidate(participants, revisions=None):
    return {
        "version": 1, "offset": 2, "reason": "",
        "expected_revisions": revisions or {item["id"]: 0 for item in participants},
        "items": [{"subject_id": participants[0]["id"], "target_id": participants[1]["id"],
                   "category": "interaction", "epistemic": "self_report", "confidence": "medium",
                   "content": "Prioritizes reliable collaboration", "rationale": "Direct statement",
                   "evidence": [{"segment_id": "segment-0", "quote": "I prioritize reliability"}]}],
    }


def apply(claimed, artifact, participants):
    return profile_db.apply_profiles(*claimed, artifact, participants)


def test_new_profiles_are_synthetic_until_atomic_apply_and_replay_is_fenced(claimed, participants):
    fresh = profile_db.load_profiles(participants)
    assert [row["revision"] for row in fresh] == [0, 0]
    assert all(row["claims"] == [] and not row["deleted"] for row in fresh)
    assert profile_db.get_profile(participants[0]["id"]) is None
    artifact = candidate(participants)
    assert apply(claimed, artifact, participants) == [participants[0]["id"]]
    profile = profile_db.get_profile(participants[0]["id"])
    claim = profile["claims"][0]
    assert profile["revision"] == 1
    assert claim["meeting_id"] == claimed[0] and claim["transcript_hash"] == claimed[2]
    assert claim["source_url"] == "https://example.test/one" and claim["target_name"] == "Blair"
    assert claim["status"] == "active" and claim["correction"] is None
    record = digestion_db.get_record(claimed[0])
    assert record["profile_status"] == "done" and record["profile_artifact"]["profile_ids"] == [profile["id"]]
    assert artifact == candidate(participants)
    assert profile_db.meeting_profiles(claimed[0])["items"] == [{key: profile[key] for key in ("id", "display_name", "email", "revision")}]
    with pytest.raises(db.ClaimLostError):
        apply(claimed, artifact, participants)
    assert profile_db.get_profile(participants[0]["id"])["revision"] == 1


def test_empty_output_completes_without_inserting_profiles(claimed, participants):
    artifact = {**candidate(participants), "items": [], "reason": "No grounded participant claims"}
    assert apply(claimed, artifact, participants) == []
    assert profile_db.meeting_profiles(claimed[0]) == {
        "status": "done", "items": [], "reason": "No grounded participant claims", "error_type": None,
    }
    assert all(row["revision"] == 0 for row in profile_db.load_profiles(participants))


def test_apply_and_stage_completion_roll_back_together(claimed, participants, monkeypatch):
    original = stage_db.write_progress

    def interrupted(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic transaction interruption")

    monkeypatch.setattr(stage_db, "write_progress", interrupted)
    with pytest.raises(RuntimeError):
        apply(claimed, candidate(participants), participants)
    assert profile_db.get_profile(participants[0]["id"]) is None
    assert digestion_db.get_record(claimed[0])["profile_status"] == "pending"


def test_cumulative_profiles_preserve_corrections_and_directed_target(source, claimed, participants):
    apply(claimed, candidate(participants), participants)
    first = profile_db.get_profile(participants[0]["id"])
    original_claim = copy.deepcopy(first["claims"][0])
    corrected = profile_db.correct_claim(first["id"], original_claim["id"], 1, "correct", "Values reliability when practical", "Clarified priority")
    assert corrected["revision"] == 2 and corrected["claims"][0]["content"] == original_claim["content"]
    assert corrected["claims"][0]["correction"]["content"] == "Values reliability when practical"
    digestion_db.release(claimed[0], claimed[1])
    second = ready_meeting(source, "two")
    owner = "second-profile-owner"
    digestion_db.claim_digestion([(source.provider, source.account_key)], owner)
    record = digestion_db.get_record(second)
    try:
        artifact = candidate(participants, {participants[0]["id"]: 2, participants[1]["id"]: 0})
        artifact["items"][0].update(category="perception", content="Expects Blair to communicate directly")
        profile_db.apply_profiles(second, owner, record["transcript_hash"], artifact, participants)
        updated = profile_db.get_profile(first["id"])
        assert updated["revision"] == 3 and len(updated["claims"]) == 2
        assert updated["claims"][0] == corrected["claims"][0]
        assert updated["claims"][1]["target_id"] == participants[1]["id"]
        assert updated["claims"][0]["id"] != updated["claims"][1]["id"]
    finally:
        digestion_db.release(second, owner)


def test_all_catalog_revisions_are_checked_before_any_subject_write(source, claimed, participants):
    # Seed the other catalog participant in a previous meeting.
    swapped = list(reversed(participants))
    artifact = candidate(swapped)
    artifact["items"][0]["evidence"] = [{"segment_id": "segment-1", "quote": "I value direct communication"}]
    apply(claimed, artifact, swapped)
    digestion_db.release(claimed[0], claimed[1])
    second = ready_meeting(source, "two")
    owner = "stale-profile-owner"
    digestion_db.claim_digestion([(source.provider, source.account_key)], owner)
    record = digestion_db.get_record(second)
    try:
        with pytest.raises(profile_db.ProfileRevisionConflict):
            profile_db.apply_profiles(second, owner, record["transcript_hash"], candidate(participants), participants)
        assert profile_db.get_profile(participants[0]["id"]) is None
        assert digestion_db.get_record(second)["profile_status"] == "pending"
        profile_db.reset_progress(second, owner, record["transcript_hash"])
        assert digestion_db.get_record(second)["profile_artifact"] == {}
    finally:
        digestion_db.release(second, owner)


@pytest.mark.parametrize("change", ["owner", "expired", "hash", "unavailable", "memory_pending"])
def test_profile_checkpoint_and_apply_enforce_live_prerequisites(claimed, participants, change):
    meeting_id, owner, transcript_hash = claimed
    if change == "owner":
        owner = "wrong-owner"
    elif change == "hash":
        transcript_hash = "wrong-hash"
    else:
        with get_connection() as conn, conn.cursor() as cur:
            if change == "expired":
                cur.execute("UPDATE meeting_digestions SET claim_until = clock_timestamp() - interval '1 second' WHERE meeting_id = %s", (meeting_id,))
            elif change == "unavailable":
                cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (meeting_id,))
            else:
                cur.execute("UPDATE meeting_digestions SET memory_status = 'pending' WHERE meeting_id = %s", (meeting_id,))
    with pytest.raises(db.ClaimLostError):
        profile_db.save_progress(meeting_id, owner, transcript_hash, candidate(participants))
    with pytest.raises(db.ClaimLostError):
        profile_db.apply_profiles(meeting_id, owner, transcript_hash, candidate(participants), participants)
    assert profile_db.get_profile(participants[0]["id"]) is None


def test_correction_rejection_history_and_revision_conflicts(claimed, participants):
    apply(claimed, candidate(participants), participants)
    profile = profile_db.get_profile(participants[0]["id"])
    claim = profile["claims"][0]
    rejected = profile_db.correct_claim(profile["id"], claim["id"], 1, "reject", None, "Misinterpreted statement")
    assert rejected["revision"] == 2 and rejected["claims"][0]["status"] == "rejected"
    with pytest.raises(profile_db.ProfileRevisionConflict):
        profile_db.correct_claim(profile["id"], claim["id"], 1, "correct", "New content", "Correction")
    corrected = profile_db.correct_claim(profile["id"], claim["id"], 2, "correct", "Clarified content", "New context")
    assert len(corrected["claims"][0]["corrections"]) == 2
    assert corrected["claims"][0]["content"] == claim["content"]
    assert corrected["claims"][0]["evidence"] == claim["evidence"]
    with pytest.raises(ValueError):
        profile_db.correct_claim(profile["id"], claim["id"], 3, "reject", None, "")


@pytest.mark.parametrize("action", ["correct", "reject"])
def test_internal_human_overrides_survive_source_withdrawal_without_public_evidence(claimed, participants, action):
    artifact = candidate(participants)
    artifact["items"].append({**copy.deepcopy(artifact["items"][0]), "content": "Another active observation"})
    apply(claimed, artifact, participants)
    profile = profile_db.get_profile(participants[0]["id"])
    original = profile["claims"][0]
    profile_db.correct_claim(profile["id"], original["id"], 1, action,
                             "Human clarified context" if action == "correct" else None, "Explicit human override")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (claimed[0],))

    public = profile_db.get_profile(profile["id"])
    assert public["claims"] == [] and public["revision"] == 2
    internal = profile_db.load_profiles(participants)[0]
    assert internal["revision"] == public["revision"]
    assert len(internal["claims"]) == 1
    constraint = internal["claims"][0]
    assert constraint["content"] == original["content"]
    assert constraint["status"] == ("corrected" if action == "correct" else "rejected")
    assert constraint["correction"]["reason"] == "Explicit human override"
    assert constraint["evidence"] == [] and constraint["source_url"] is None and constraint["source_unavailable"]
    assert original["evidence"][0]["quote"] not in json.dumps(internal)
    assert "Another active observation" not in json.dumps(internal)


def test_candidate_schema_rejection_does_not_echo_private_values(claimed, participants):
    artifact = candidate(participants)
    artifact["items"][0].update(category="invalid", content="private candidate secret-token")
    with pytest.raises(ValueError, match="output schema") as caught:
        apply(claimed, artifact, participants)
    assert "private candidate" not in str(caught.value) and "secret-token" not in str(caught.value)


def test_deleted_profile_is_tombstoned_and_cannot_be_recreated(source, claimed, participants):
    apply(claimed, candidate(participants), participants)
    profile_id = participants[0]["id"]
    with pytest.raises(profile_db.ProfileRevisionConflict):
        profile_db.delete_profile(profile_id, 2)
    profile_db.delete_profile(profile_id, 1)
    assert profile_db.get_profile(profile_id) is None
    tombstone = profile_db.load_profiles(participants)[0]
    assert tombstone["deleted"] and tombstone["revision"] == 2 and tombstone["claims"] == []
    assert profile_db.meeting_profiles(claimed[0])["items"] == []
    digestion_db.release(claimed[0], claimed[1])
    second = ready_meeting(source, "two")
    owner = "deleted-profile-owner"
    digestion_db.claim_digestion([(source.provider, source.account_key)], owner)
    record = digestion_db.get_record(second)
    try:
        artifact = candidate(participants, {profile_id: 2, participants[1]["id"]: 0})
        with pytest.raises(profile_db.ProfileRevisionConflict):
            profile_db.apply_profiles(second, owner, record["transcript_hash"], artifact, participants)
        assert profile_db.get_profile(profile_id) is None
        artifact["items"] = []
        profile_db.apply_profiles(second, owner, record["transcript_hash"], artifact, participants)
        assert digestion_db.get_record(second)["profile_status"] == "done"
    finally:
        digestion_db.release(second, owner)


def test_unavailable_source_claims_are_hidden_but_preserved_canonically(claimed, participants):
    apply(claimed, candidate(participants), participants)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_summaries SET available = false WHERE id = %s", (claimed[0],))
    assert profile_db.meeting_profiles(claimed[0]) is None
    assert profile_db.get_profile(participants[0]["id"])["claims"] == []
    assert profile_db.load_profiles(participants)[0]["claims"] == []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT claims FROM participant_profiles WHERE id = %s", (participants[0]["id"],))
        assert len(cur.fetchone()[0]) == 1


def test_failures_are_bounded_safe_and_retry_only_reopens_profile_stage(claimed):
    meeting_id, owner, _ = claimed
    for attempt in range(1, 4):
        profile_db.record_failure(meeting_id, owner, "AgentValidationError")
        row = digestion_db.get_record(meeting_id)
        assert row["profile_attempts"] == attempt
        assert row["profile_status"] == ("failed" if attempt == 3 else "pending")
        assert row["profile_error"] == "AgentValidationError"
        assert row["memory_status"] == "done"
    profile_db.retry_profiles(meeting_id)
    row = digestion_db.get_record(meeting_id)
    assert row["profile_status"] == "pending" and row["profile_attempts"] == 0
    assert row["memory_status"] == "done"
    with pytest.raises(ValueError):
        profile_db.retry_profiles(meeting_id)
    with pytest.raises(ValueError):
        profile_db.record_failure(meeting_id, owner, "private error body")


@pytest.mark.parametrize("invalid", ["unknown_subject", "unknown_target", "forged_quote", "other_speaker", "inference_high", "missing_revision"])
def test_invalid_claims_fail_before_any_canonical_write(claimed, participants, invalid):
    artifact = candidate(participants)
    item = artifact["items"][0]
    if invalid == "unknown_subject":
        item["subject_id"] = str(uuid4())
    elif invalid == "unknown_target":
        item["target_id"] = str(uuid4())
    elif invalid == "forged_quote":
        item["evidence"][0]["quote"] = "Invented quote"
    elif invalid == "other_speaker":
        item["evidence"] = [{"segment_id": "segment-1", "quote": "I value direct communication"}]
    elif invalid == "inference_high":
        item.update(epistemic="inference", confidence="high")
    else:
        artifact["expected_revisions"].pop(participants[1]["id"])
    with pytest.raises(ValueError):
        apply(claimed, artifact, participants)
    assert profile_db.get_profile(participants[0]["id"]) is None
    assert digestion_db.get_record(claimed[0])["profile_status"] == "pending"


def test_profile_status_exposes_missing_dependencies_and_legacy(source):
    meeting_id = enroll(source, note())
    assert profile_db.meeting_profiles(meeting_id)["reason"] == "transcript_pending"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE meeting_digestions SET transcript_status = 'ready' WHERE meeting_id = %s", (meeting_id,))
    assert profile_db.meeting_profiles(meeting_id)["reason"] == "memories_pending"
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM meeting_digestions WHERE meeting_id = %s", (meeting_id,))
    assert profile_db.meeting_profiles(meeting_id)["status"] == "not_imported"


def test_same_name_different_identity_remains_separate(claimed, participants):
    participants[1] = {**participants[1], "display_name": participants[0]["display_name"]}
    artifact = candidate(participants)
    reverse = copy.deepcopy(artifact["items"][0])
    reverse.update(subject_id=participants[1]["id"], target_id=participants[0]["id"], content="Communicates directly",
                   evidence=[{"segment_id": "segment-1", "quote": "I value direct communication"}])
    artifact["items"].append(reverse)
    apply(claimed, artifact, participants)
    profiles = profile_db.load_profiles(participants)
    assert profiles[0]["id"] != profiles[1]["id"]
    assert all(len(row["claims"]) == 1 and row["revision"] == 1 for row in profiles)


def test_stage_names_are_allowlisted():
    with pytest.raises(ValueError, match="Unknown meeting stage"):
        stage_db.record_failure("memory; DELETE", "irrelevant", "owner", "Error")


def test_cumulative_size_limit_rolls_back_new_claim_and_stage(source, claimed, participants):
    from psycopg2.extras import Json

    apply(claimed, candidate(participants), participants)
    profile = profile_db.get_profile(participants[0]["id"])
    profile["claims"][0]["content"] = "private historical text " * 90_000
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE participant_profiles SET claims = %s WHERE id = %s", (Json(profile["claims"]), profile["id"]))
    digestion_db.release(claimed[0], claimed[1])
    second = ready_meeting(source, "two")
    owner = "oversized-profile-owner"
    digestion_db.claim_digestion([(source.provider, source.account_key)], owner)
    record = digestion_db.get_record(second)
    try:
        artifact = candidate(participants, {participants[0]["id"]: 1, participants[1]["id"]: 0})
        with pytest.raises(ValueError, match="2000000-byte storage limit") as failed:
            profile_db.apply_profiles(second, owner, record["transcript_hash"], artifact, participants)
        assert "private historical" not in str(failed.value)
        assert profile_db.get_profile(profile["id"])["revision"] == 1
        assert digestion_db.get_record(second)["profile_status"] == "pending"
    finally:
        digestion_db.release(second, owner)


def test_concurrent_correction_and_candidate_apply_have_one_revision_winner(source, claimed, participants):
    apply(claimed, candidate(participants), participants)
    profile = profile_db.get_profile(participants[0]["id"])
    digestion_db.release(claimed[0], claimed[1])
    second = ready_meeting(source, "two")
    owner = "concurrent-profile-owner"
    digestion_db.claim_digestion([(source.provider, source.account_key)], owner)
    record = digestion_db.get_record(second)
    barrier = threading.Barrier(2)

    def edit():
        barrier.wait(timeout=5)
        try:
            profile_db.correct_claim(profile["id"], profile["claims"][0]["id"], 1, "reject", None, "User correction")
            return "edit"
        except profile_db.ProfileRevisionConflict:
            return "conflict"

    def automated_apply():
        barrier.wait(timeout=5)
        try:
            profile_db.apply_profiles(second, owner, record["transcript_hash"], candidate(participants, {
                participants[0]["id"]: 1, participants[1]["id"]: 0,
            }), participants)
            return "apply"
        except profile_db.ProfileRevisionConflict:
            return "conflict"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(action) for action in (edit, automated_apply)]
            outcomes = [future.result(timeout=5) for future in futures]
        assert outcomes.count("conflict") == 1
        updated = profile_db.get_profile(profile["id"])
        assert updated["revision"] == 2
        if "edit" in outcomes:
            assert updated["claims"][0]["status"] == "rejected" and len(updated["claims"]) == 1
            assert digestion_db.get_record(second)["profile_status"] == "pending"
        else:
            assert len(updated["claims"]) == 2
            assert digestion_db.get_record(second)["profile_status"] == "done"
    finally:
        digestion_db.release(second, owner)
