from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from services.meetings.types import MeetingSummary, TranscriptPage, TranscriptSegment


def _summary(metadata):
    stamp = datetime(2026, 1, 27, 15, 30, tzinfo=timezone.utc)
    return MeetingSummary(
        external_id="not_1d3tmYTlCICgjy", title="Meeting", summary_text="Agreed next steps.",
        summary_markdown=None, source_url="https://notes.granola.ai/d/test",
        provider_created_at=stamp, provider_updated_at=stamp, metadata=metadata,
    )


@pytest.mark.parametrize("field", ["attendees", "folder_membership", "space_membership", "invitees"])
def test_meeting_hash_ignores_unordered_metadata_reordering_without_mutation(field):
    members = [{"email": "b@example.test", "name": "B"}, {"name": "A", "email": "a@example.test"}]
    metadata = {"calendar_event": {"invitees": members}} if field == "invitees" else {field: members}
    reordered = deepcopy(metadata)
    target = reordered["calendar_event"][field] if field == "invitees" else reordered[field]
    target.reverse()
    original = deepcopy(metadata)
    original_reordered = deepcopy(reordered)

    assert _summary(metadata).payload_hash() == _summary(reordered).payload_hash()
    assert metadata == original
    assert reordered == original_reordered


def test_meeting_hash_preserves_unrecognized_array_order():
    first = _summary({"custom_steps": ["first", "second"], "calendar_event": {"custom_steps": [1, 2]}})
    assert first.payload_hash() != replace(first, metadata={"custom_steps": ["second", "first"], "calendar_event": {"custom_steps": [1, 2]}}).payload_hash()
    assert first.payload_hash() != replace(first, metadata={"custom_steps": ["first", "second"], "calendar_event": {"custom_steps": [2, 1]}}).payload_hash()


def test_meeting_hash_detects_changed_membership_and_ignores_ingestion_timestamps():
    first = _summary({"attendees": [{"email": "a@example.test"}]})
    assert first.payload_hash() != replace(first, metadata={"attendees": [{"email": "b@example.test"}]}).payload_hash()
    assert first.payload_hash() == replace(first, provider_updated_at=datetime(2026, 2, 1, tzinfo=timezone.utc)).payload_hash()


def test_transcript_segment_serializes_stable_evidence_id_without_mutating_speaker():
    stamp = datetime(2026, 1, 27, 15, 30, tzinfo=timezone.utc)
    segment = TranscriptSegment("A decision", {"diarization_label": "Speaker A"}, stamp)
    result = segment.to_dict(7)
    assert result == {
        "id": "segment-7", "text": "A decision", "speaker": {"diarization_label": "Speaker A"},
        "start_time": stamp.isoformat(), "end_time": None,
    }
    result["speaker"]["name"] = "Not established"
    assert "name" not in segment.speaker
    assert TranscriptPage((segment,)).segments == (segment,)


@pytest.mark.parametrize("index", [-1, True, None, "1"])
def test_transcript_segment_rejects_invalid_evidence_index(index):
    with pytest.raises(ValueError, match="nonnegative integer"):
        TranscriptSegment("A decision", {}).to_dict(index)
