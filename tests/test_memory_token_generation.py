from __future__ import annotations

import json
from copy import deepcopy
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from services.meetings import analysis as memory_analysis, memory_pass
from services.meetings.analysis import MemoryAnalysisError, analyze_memories
from services.meetings.outputs import MemoryItem
from services.memory.content import MemoryTokenBudget
from services.memory import db
from tests.test_memory_content import content_store as content_store
from tests.test_meeting_memory_agent import (
    ITEM,
    SNAPSHOT,
    SUMMARY,
    backend as backend,
    call,
    model as model,
)


@pytest.fixture(autouse=True)
def token_budget(monkeypatch):
    budget = MemoryTokenBudget(256, 2, lambda content: len(content) + 2)
    monkeypatch.setattr(memory_analysis, "get_memory_token_budget", lambda: budget)
    return budget


def snapshot(summary=SUMMARY, **changes):
    return {
        **SNAPSHOT,
        "source_url": "https://example.test/source",
        "summary_text": summary,
        **changes,
    }


def test_typed_generated_drafts_are_not_silently_clipped_before_staging():
    content = " ".join(["confirmed"] * 251) + " FINAL_COMPLETE_FACT"
    candidate = MemoryItem.model_validate({**ITEM, "content": content})
    assert candidate.content == content


def test_complete_publication_builder_preserves_the_full_body_and_exact_evidence():
    candidate = {
        **ITEM,
        "source": "summary",
        "content": " ".join(["confirmed"] * 251) + " FINAL_COMPLETE_FACT",
    }
    before = deepcopy(candidate)
    full = memory_pass.memory_content(snapshot(), candidate)
    assert full.startswith(candidate["content"])
    assert full.endswith(
        "\n\nMeeting source: https://example.test/source\nEvidence: Granola summary (summary-4)"
    )
    assert candidate == before


@pytest.mark.asyncio
async def test_real_tool_loop_rejects_complete_oversize_then_preserves_a_supported_rewrite(
    backend, model, token_budget
):
    quote = "Full supported evidence. " * 50 + "EXACT_EVIDENCE_TAIL"
    source = SUMMARY + "\n" + quote
    oversized = {
        **ITEM,
        "content": "Confirmed release identifiers and constraints. " * 15,
        "evidence": [{"segment_id": "summary-4", "quote": quote}],
    }
    rewritten = {**oversized, "content": "The team decided to ship on Friday."}
    instance, _ = model(
        [
            call("search_previous_memories", query="release"),
            call("stage_memories", items=[oversized]),
            call("stage_memories", items=[rewritten]),
            AIMessage(content="Unused final prose"),
        ]
    )
    result = await analyze_memories(
        snapshot(source), [{"id": "summary-4", "text": source}], []
    )
    assert result["items"] == [rewritten]
    assert len(instance.seen) == 3
    feedback = [
        message.content
        for message in instance.seen[-1]
        if isinstance(message, ToolMessage) and message.name == "stage_memories"
    ]
    assert len(feedback) == 1
    error = json.loads(feedback[0])["error"]
    assert "allowance" in error and "256" in error and "Rewrite" in error
    assert (
        "Confirmed release identifiers" not in error and "EXACT_EVIDENCE" not in error
    )
    system = next(
        message.content
        for message in instance.seen[0]
        if isinstance(message, SystemMessage)
    )
    assert "256" in system and "254" in system and "embedding" in system
    complete = memory_pass.memory_content(
        snapshot(source), {**rewritten, "source": "summary"}
    )
    assert token_budget.total_tokens(complete) <= 256
    assert result["items"][0]["evidence"][0]["quote"] == quote
    assert backend[2] == []


@pytest.mark.asyncio
async def test_first_pass_fitting_generation_stays_exact(backend, model):
    instance, _ = model(
        [
            call("search_previous_memories", query="release"),
            call("stage_memories", items=[ITEM]),
        ]
    )
    result = await analyze_memories(
        snapshot(), [{"id": "summary-4", "text": SUMMARY}], []
    )
    assert result["items"] == [ITEM] and len(instance.seen) == 2
    assert backend[2] == []


@pytest.mark.asyncio
async def test_existing_optional_source_projection_keeps_generation_and_footer_semantics(
    backend, model
):
    model(
        [
            call("search_previous_memories", query="release"),
            call("stage_memories", items=[ITEM]),
        ]
    )
    context = snapshot(source_url=None)
    result = await analyze_memories(context, [{"id": "summary-4", "text": SUMMARY}], [])
    assert result["items"] == [ITEM]
    assert "Meeting source: None\n" in memory_pass.memory_content(
        context, {**ITEM, "source": "summary"}
    )
    assert backend[2] == []


@pytest.mark.asyncio
async def test_impossible_frozen_source_footer_fails_before_model_or_search(
    backend, model
):
    instance, roles = model([AIMessage(content="Must not run")])
    with pytest.raises(ValueError, match="footer leaves no room"):
        await analyze_memories(
            snapshot(source_url="https://example.test/" + "private-source-" * 60),
            [{"id": "summary-4", "text": SUMMARY}],
            [],
        )
    assert instance.seen == [] and roles == []
    assert backend[0] == backend[2] == []


@pytest.mark.asyncio
async def test_repeated_invalid_staging_never_publishes_a_partial_memory(
    backend, model
):
    oversized = {**ITEM, "content": "Confirmed release constraints. " * 20}
    model(
        [
            call("search_previous_memories", query="release"),
            call("stage_memories", items=[oversized]),
            AIMessage(content="Done"),
        ]
    )
    with pytest.raises(MemoryAnalysisError, match="without a valid staged result"):
        await analyze_memories(snapshot(), [{"id": "summary-4", "text": SUMMARY}], [])
    assert backend[2] == []


@pytest.mark.asyncio
async def test_selected_citation_cost_requires_revision_without_shortening_evidence(
    backend, model
):
    long_id = "summary-" + "1" * 170
    quote = ITEM["evidence"][0]["quote"]
    oversized = {**ITEM, "evidence": [{"segment_id": long_id, "quote": quote}]}
    instance, _ = model(
        [
            call("search_previous_memories", query="release"),
            call("stage_memories", items=[oversized]),
            call("stage_memories", items=[ITEM]),
        ]
    )
    result = await analyze_memories(
        snapshot(),
        [{"id": long_id, "text": SUMMARY}, {"id": "summary-4", "text": SUMMARY}],
        [],
    )
    assert result["items"] == [ITEM] and len(instance.seen) == 3
    feedback = next(
        message.content
        for message in instance.seen[-1]
        if isinstance(message, ToolMessage) and message.name == "stage_memories"
    )
    assert "footer tokens" in feedback and long_id not in feedback
    assert result["items"][0]["evidence"][0]["quote"] == quote
    assert backend[2] == []


@pytest.mark.asyncio
async def test_actual_staged_publication_embeds_and_stores_its_complete_fitting_envelope(
    content_store, model, monkeypatch, token_budget
):
    backend, embeddings = content_store
    monkeypatch.setattr(embeddings, "memory_token_budget", lambda: token_budget)
    model(
        [
            call("search_previous_memories", query="release"),
            call("stage_memories", items=[ITEM]),
        ]
    )
    context = snapshot()
    result = await analyze_memories(context, [{"id": "summary-4", "text": SUMMARY}], [])
    id = str(uuid4())
    candidate = {**result["items"][0], "id": id, "source": "summary"}
    artifact = {
        "version": 1,
        "items": [candidate],
        "published_ids": [],
        "created_at": "2026-11-05T12:00:00Z",
    }
    memory_pass.freeze_publications(artifact, context["id"], context)
    envelope = deepcopy(artifact["publication_envelopes"][id])
    embeddings.documents.clear()
    assert db.publish(id, **envelope) == id
    stored = backend.get_row(id)
    assert stored["text"] == envelope["content"]
    assert stored["text"].startswith(ITEM["content"])
    assert stored["text"].endswith("Evidence: Granola summary (summary-4)")
    assert embeddings.documents == [stored["text"]]
    assert token_budget.total_tokens(stored["text"]) <= 256
    assert artifact["publication_envelopes"][id] == envelope
    assert artifact["items"][0]["evidence"] == ITEM["evidence"]
