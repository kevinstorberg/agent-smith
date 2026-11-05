from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import analysis, digestion_db, enrichment, memory_db, memory_pass
from services.meetings.outputs import Evidence, MemoryItem, ProfileClaim
from services.memory import db as vector_db
from tests.test_meeting_memory_flow import feed as feed, ready as ready
from tests.test_meeting_sync import source as source
from tests.test_memory_content import CREATED, content_store as content_store

BODY = " ".join(f"word{index}" for index in range(250))
QUOTE = " ".join(f"q{index}" for index in range(251)) + " EXACT_EVIDENCE_TAIL"


def item():
    return {
        "id": str(uuid4()),
        "content": BODY + " EXTRA_BODY_TAIL",
        "kind": "decision",
        "tags": ["product"],
        "source": "summary",
        "evidence": [{"segment_id": "summary-0", "quote": QUOTE}],
    }


def artifact(*items):
    return {
        "version": 1,
        "items": list(items),
        "published_ids": [],
        "created_at": CREATED,
        "offset": 1,
        "total_units": 1,
        "reason": "",
        "publication_envelopes": {},
    }


def test_new_meeting_payload_reserves_actual_footer_words_and_preserves_exact_evidence():
    candidate = item()
    candidate["evidence"] += [
        {"segment_id": f"summary-{index}", "quote": "unchanged"}
        for index in range(1, 10)
    ]
    before = deepcopy(candidate)
    snapshot = {"source_url": "https://example.test/full-source", "project": "project"}
    frozen = artifact(candidate)
    memory_pass.freeze_publications(frozen, str(uuid4()), snapshot)
    content = frozen["publication_envelopes"][candidate["id"]]["content"]
    assert len(content.split()) == 250
    assert content.endswith(
        "\n\nMeeting source: https://example.test/full-source\nEvidence: Granola summary ("
        + ", ".join(f"summary-{index}" for index in range(10))
        + ")"
    )
    assert frozen["items"] == [before]
    assert "EXTRA_BODY_TAIL" not in content


def test_mandatory_footer_must_leave_room_for_body_without_changing_frozen_envelopes():
    candidate = item()
    frozen = artifact(candidate)
    before = deepcopy(frozen)
    snapshot = {"source_url": " ".join(["source"] * 250), "project": "project"}
    with pytest.raises(ValueError, match="footer leaves no room"):
        memory_pass.freeze_publications(frozen, str(uuid4()), snapshot)
    assert frozen == before


def test_existing_publication_envelopes_and_receipts_remain_immutable(content_store):
    backend, embeddings = content_store
    candidate = item()
    meeting_id = str(uuid4())
    frozen = artifact(candidate)
    envelope = {
        "content": BODY
        + " OLD_TAIL\n\nMeeting source: https://example.test/legacy\nEvidence: summary-0",
        "repo": "legacy",
        "tags": ["product"],
        "created_at": CREATED,
        "source_type": "meeting",
        "source_id": meeting_id,
    }
    frozen["publication_envelopes"][candidate["id"]] = deepcopy(envelope)
    before = deepcopy(frozen)
    memory_pass.freeze_publications(
        frozen, meeting_id, {"source_url": "https://changed.invalid", "project": "new"}
    )
    assert frozen == before
    vector_db.publish(
        candidate["id"], **frozen["publication_envelopes"][candidate["id"]]
    )
    assert backend.get_row(candidate["id"])["text"] == BODY
    assert embeddings.documents == [BODY]
    assert frozen == before
    frozen["published_ids"].append(candidate["id"])
    acknowledged = deepcopy(frozen)
    memory_pass.freeze_publications(frozen, meeting_id, None)
    assert frozen == acknowledged


def test_only_memory_body_is_capped_and_existing_character_contracts_remain():
    evidence = {"segment_id": "summary-0", "quote": QUOTE}
    memory = MemoryItem(
        content=BODY + " EXTRA", kind="fact", tags=["product"], evidence=[evidence]
    )
    profile = ProfileClaim(
        subject_id="person",
        category="priority",
        epistemic="observed",
        confidence="high",
        content=QUOTE,
        evidence=[evidence],
    )
    assert memory.content == BODY
    assert (
        Evidence(**evidence).quote
        == profile.content
        == profile.evidence[0].quote
        == QUOTE
    )
    with pytest.raises(ValueError):
        MemoryItem(
            content="x" * 4001, kind="fact", tags=["product"], evidence=[evidence]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("lost", ["ack", "receipt"])
async def test_native_lost_publication_replays_same_capped_envelope_and_id_without_agent(
    content_store, source, ready, monkeypatch, lost
):
    backend, embeddings = content_store
    candidate = item()
    frozen = artifact(candidate)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_digestions SET memory_artifact=%s WHERE meeting_id=%s",
            (Json(frozen), ready),
        )
    snapshot = digestion_db.get_record(ready)["snapshot"]
    expected = memory_pass.publication_payload(ready, snapshot, frozen, candidate)
    failures = []
    original_publish, original_save = vector_db.publish, memory_db.save_progress

    async def forbidden(*args, **kwargs):
        raise AssertionError("Publication replay must not call an agent")

    monkeypatch.setattr(analysis, "analyze_memories", forbidden)
    if lost == "ack":

        def publish(*args, **kwargs):
            result = original_publish(*args, **kwargs)
            if not failures:
                failures.append(True)
                raise RuntimeError("Synthetic lost ACK")
            return result

        monkeypatch.setattr(vector_db, "publish", publish)
    else:

        def save(*args, **kwargs):
            if args[3]["published_ids"] and not failures:
                failures.append(True)
                raise RuntimeError("Synthetic lost receipt")
            return original_save(*args, **kwargs)

        monkeypatch.setattr(memory_db, "save_progress", save)
    async with enrichment.DigestionRun(source.name) as run:
        await run.prepare()
        await run.generate_memories()
        assert run.memory_report["outcome"] == "failed"
    first = digestion_db.get_record(ready)["memory_artifact"]
    stored = deepcopy(backend.get_row(candidate["id"]))
    assert first["publication_envelopes"] == {candidate["id"]: expected}
    assert first["published_ids"] == []
    assert stored["text"] == expected["content"] and len(stored["text"].split()) == 250
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE meeting_digestions SET memory_next_attempt_at=clock_timestamp() WHERE meeting_id=%s",
            (ready,),
        )
    async with enrichment.DigestionRun(source.name) as run:
        await run.prepare()
        await run.generate_memories()
        assert run.memory_report["outcome"] == "done"
    final = digestion_db.get_record(ready)["memory_artifact"]
    assert final["publication_envelopes"] == first["publication_envelopes"]
    assert final["published_ids"] == [candidate["id"]]
    assert final["items"] == [candidate]
    assert backend.get_row(candidate["id"]) == stored
    assert embeddings.documents == [expected["content"]]
