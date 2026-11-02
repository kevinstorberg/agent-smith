from copy import deepcopy

import pytest

from services.meetings import enrichment


def test_summary_windows_freeze_the_complete_input_and_exclude_transcript(monkeypatch):
    monkeypatch.setattr(enrichment, "WINDOW_CHARS", 12)
    record = {
        "snapshot": {"summary_text": "Granola decision: release Friday.", "revision": 3},
        "transcript": {"segments": [{"id": "segment-0", "text": "Transcript-only detail."}]},
    }
    original = deepcopy(record)
    artifact = {"input_source": "summary"}
    snapshot, sections = enrichment.memory_input(record, artifact)
    assert snapshot["memory_source"] == "summary"
    assert "".join(section["text"] for section in sections) == original["snapshot"]["summary_text"]
    assert [section["id"] for section in sections] == ["summary-0", "summary-1", "summary-2"]
    record["snapshot"]["summary_text"] = "A later summary with a different decision."
    record["snapshot"]["revision"] = 4
    assert enrichment.memory_input(record, artifact) == (snapshot, sections)
    artifact["input_snapshot"]["summary_text"] = "A corrupted frozen summary."
    with pytest.raises(ValueError, match="frozen input hash"):
        enrichment.memory_input(record, artifact)


def test_unmarked_checkpoint_keeps_its_transcript_input():
    record = {"snapshot": {"summary_text": "Summary."},
              "transcript": {"segments": [{"id": "segment-7", "text": "Original transcript evidence."}]}}
    snapshot, sections = enrichment.memory_input(record, {"version": 1, "offset": 1})
    assert snapshot == record["snapshot"]
    assert sections == record["transcript"]["segments"]


def test_whitespace_only_summary_chunks_do_not_require_an_agent_call(monkeypatch):
    monkeypatch.setattr(enrichment, "WINDOW_CHARS", 5)
    record = {"snapshot": {"summary_text": "abcde     fghij "}}
    artifact = {"input_source": "summary"}
    snapshot, sections = enrichment.memory_input(record, artifact)
    assert sections == [{"id": "summary-0", "text": "abcde"}, {"id": "summary-2", "text": "fghij"}]
    assert snapshot["summary_text"] == artifact["input_snapshot"]["summary_text"] == "abcde     fghij "


@pytest.mark.parametrize("source,summary,message", [
    ("summary", "  ", "nonblank saved Granola summary"),
    ("summary", None, "nonblank saved Granola summary"),
    ("unknown", "Summary", "Unsupported meeting memory input source"),
])
def test_invalid_memory_source_fails_before_extraction(source, summary, message):
    with pytest.raises(ValueError, match=message):
        enrichment.memory_input({"snapshot": {"summary_text": summary}}, {"input_source": source})


def test_summary_publication_is_explicit_and_legacy_publication_remains_identical():
    snapshot = {"source_url": "https://notes.granola.ai/d/example"}
    legacy = {"content": "Original fact", "evidence": [{"segment_id": "segment-4", "quote": "Original"}]}
    assert enrichment.memory_content(snapshot, legacy) == (
        "Original fact\n\nMeeting source: https://notes.granola.ai/d/example\nEvidence: segment-4"
    )
    summary = {**legacy, "source": "summary", "evidence": [{"segment_id": "summary-0", "quote": "Original"}]}
    assert enrichment.memory_content(snapshot, summary).endswith("Evidence: Granola summary (summary-0)")
