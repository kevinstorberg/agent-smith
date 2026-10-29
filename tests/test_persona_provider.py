import copy
import json

import pytest

from services.graphs.library.persona import PersonaProcessingError
from services.graphs.runtime import dispatch
from services.jobs.service import has_requested_work
from services.meetings import digestion_db, profile_analysis, profile_db, stage_db
from services.personas import factory


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "dependency", "conflict"])
async def test_persona_provider_owns_storage_for_nonmeeting_context(monkeypatch, failure, extraction_only):
    context_id = "synthetic-messages:thread-42"
    row = {
        "context_id": context_id, "context_hash": "frozen-synthetic-content",
        "segments": [{"id": "message-1", "text": "A synthetic observation", "speaker": {"name": "Synthetic"}}],
        "snapshot": {"source_type": "synthetic-messages"}, "participants_revision": 0,
        "profile_artifact": {}, "profile_status": "pending", "profile_attempts": 0,
    }
    calls = []

    class Provider:
        def claim(self, owner, *, source=None):
            assert source == "saved-channel"
            calls.append(("claim", owner))
            return copy.deepcopy(row)

        def has_requested_work(self, *, source=None):
            assert source == "saved-channel"
            calls.append(("due",))
            return row["profile_status"] == "pending"

        def get_record(self, key):
            assert key == context_id
            calls.append(("read",))
            return copy.deepcopy(row)

        def prepare_context(self, record):
            assert record["context_hash"] == row["context_hash"]
            calls.append(("context",))
            return record["snapshot"], [], []

        def save_progress(self, key, owner, content_hash, artifact):
            assert key == context_id and content_hash == row["context_hash"]
            calls.append(("checkpoint", artifact["offset"]))
            row["profile_artifact"] = copy.deepcopy(artifact)

        def apply_profiles(self, key, owner, content_hash, artifact, participants):
            assert key == context_id and content_hash == row["context_hash"] and participants == []
            calls.append(("apply",))
            if failure == "conflict":
                raise profile_db.ProfileRevisionConflict("private synthetic conflict")
            row.update(profile_status="done", profile_artifact={**artifact, "profile_ids": []})
            return []

        def reset_progress(self, key, owner, content_hash):
            assert key == context_id and content_hash == row["context_hash"]
            calls.append(("reset",))
            row["profile_artifact"] = {}

        def record_failure(self, key, owner, error_type):
            assert key == context_id
            calls.append(("failure", error_type))
            row["profile_attempts"] += 1

        def release_owner(self, owner):
            calls.append(("release", owner))

    async def analyze(snapshot, segments, previous, **kwargs):
        assert snapshot["source_type"] == "synthetic-messages" and segments[0]["id"] == "message-1"
        if failure == "dependency":
            raise profile_analysis.ProfileAnalysisError("private synthetic response", error_type="SyntheticDependencyError")
        return {"items": [], "reason": "No grounded profile addition"}

    def forbidden(*args, **kwargs):
        raise AssertionError("A nonmeeting adapter must not access meeting storage")

    monkeypatch.setitem(factory._PROVIDERS, "synthetic", Provider)
    monkeypatch.setenv("PERSONA_CONTEXT_PROVIDER", "synthetic")
    monkeypatch.setattr(profile_analysis, "analyze_profiles", analyze)
    for module in (digestion_db, profile_db, stage_db):
        monkeypatch.setattr(module, "_cursor", forbidden)
    assert has_requested_work({"input_params": {"graph_type": "persona", "graph_inputs": {"source": "saved-channel"}}})
    if failure:
        with pytest.raises(PersonaProcessingError) as caught:
            await dispatch("persona", {"source": "saved-channel"})
        assert "private" not in str(caught.value)
        assert row["profile_attempts"] == 1
        expected = "ProfileRevisionConflict" if failure == "conflict" else "SyntheticDependencyError"
        assert ("failure", expected) in calls
        assert (("reset",) in calls) == (failure == "conflict")
    else:
        report = json.loads(await dispatch("persona", {"source": "saved-channel"}))["profiles"]
        assert report["outcome"] == "done" and report["context_id"] == context_id and "meeting_id" not in report
        assert ("checkpoint", 0) in calls and ("checkpoint", 1) in calls and ("apply",) in calls
        assert row["profile_status"] == "done"
    assert calls[-1][0] == "release" and calls[-1][1] == next(call[1] for call in calls if call[0] == "claim")
