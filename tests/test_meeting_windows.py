from copy import deepcopy

from services.meetings.enrichment import WINDOW_CHARS, WINDOW_SEGMENTS, expanded_segments, transcript_window


def test_large_segment_preserves_all_text_and_original_evidence_identity():
    original = [{
        "id": "segment-7", "text": "前" * WINDOW_CHARS + "Exact final evidence.",
        "speaker": {"diarization_label": "Speaker A"}, "start_time": "2026-01-01T12:00:00+00:00", "end_time": None,
    }]
    before = deepcopy(original)
    pieces = expanded_segments(original)
    assert original == before
    assert len(pieces) == 2
    assert "".join(piece["text"] for piece in pieces) == original[0]["text"]
    assert all(piece["id"] == original[0]["id"] and piece["speaker"] == original[0]["speaker"] for piece in pieces)
    assert pieces[-1]["text"] == "Exact final evidence."
    assert expanded_segments(original) == pieces


def test_windows_cover_every_expanded_piece_once_and_resume_from_durable_offset():
    segments = [
        {"id": "segment-0", "text": "Opening statement."},
        {"id": "segment-1", "text": "a" * (WINDOW_CHARS * 2) + "Last part of the long statement."},
        {"id": "segment-2", "text": "Closing statement."},
        {"id": "segment-3", "text": ""},
    ]
    pieces = expanded_segments(segments)
    visited, offset = [], 0
    while offset < len(pieces):
        window, next_offset = transcript_window(pieces, offset)
        assert next_offset > offset
        assert len({segment["id"] for segment in window}) == len(window)
        assert sum(len(segment["text"]) for segment in window) <= WINDOW_CHARS
        assert transcript_window(expanded_segments(segments), offset) == (window, next_offset)
        visited.extend(window)
        offset = next_offset
    assert visited == pieces
    for segment in segments:
        assert "".join(item["text"] for item in visited if item["id"] == segment["id"]) == segment["text"]
    assert transcript_window(pieces, offset) == ([], len(pieces))


def test_two_pieces_of_one_canonical_segment_never_share_a_window():
    pieces = [{"id": "segment-0", "text": "first"}, {"id": "segment-0", "text": "second"}]
    assert transcript_window(pieces, 0) == (pieces[:1], 1)
    assert transcript_window(pieces, 1) == (pieces[1:], 2)


def test_short_and_empty_segments_cannot_create_an_unbounded_metadata_window():
    segments = [{"id": f"segment-{index}", "text": ""} for index in range(WINDOW_SEGMENTS + 1)]
    first, offset = transcript_window(expanded_segments(segments), 0)
    assert first == segments[:WINDOW_SEGMENTS] and offset == WINDOW_SEGMENTS
    assert transcript_window(expanded_segments(segments), offset) == (segments[WINDOW_SEGMENTS:], len(segments))
