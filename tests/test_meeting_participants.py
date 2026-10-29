from uuid import uuid4

from services.meetings.participants import meeting_participants


def snapshot(attendees=None):
    return {"id": str(uuid4()), "metadata": {"attendees": attendees or []}}


def segment(index, **speaker):
    return {"id": f"segment-{index}", "speaker": speaker, "text": "Recorded words"}


def test_explicit_named_speakers_reuse_one_normalized_email_across_meetings():
    first = snapshot([{"name": "Alice", "email": " Alice+Meetings@Example.com "}])
    segments = [segment(0, name="Alice"), segment(1, name="Alice")]
    person = meeting_participants(first, segments)[0]
    second = snapshot([{"name": "Alice", "email": "alice+meetings@example.com"}])
    assert meeting_participants(second, segments)[0]["id"] == person["id"]
    assert person["email"] == "alice+meetings@example.com"
    assert person["segment_ids"] == ["segment-0", "segment-1"]
    assert person["identity_scope"] == "email"


def test_same_name_different_emails_and_ambiguous_roster_remain_separate():
    first = snapshot([{"name": "Alex", "email": "one@example.com"}])
    second = snapshot([{"name": "Alex", "email": "two@example.com"}])
    spoken = [segment(0, name="Alex")]
    assert meeting_participants(first, spoken)[0]["id"] != meeting_participants(second, spoken)[0]["id"]
    first["metadata"]["attendees"].append(second["metadata"]["attendees"][0])
    assert meeting_participants(first, spoken)[0]["identity_scope"] == "meeting"


def test_anonymous_speakers_and_shared_microphones_are_never_guessed_from_roster():
    meeting = snapshot([{"name": "Alice", "email": "alice@example.com"}])
    people = meeting_participants(meeting, [
        segment(0, name="Them", source="system", diarization_label="Speaker 1"),
        segment(1, source="microphone"), segment(2),
        segment(3, name="Me", diarization_label="Speaker 2"),
    ])
    assert len(people) == 2 and all(person["email"] is None for person in people)
    assert {person["display_name"] for person in people} == {"Speaker 1", "Speaker 2"}
    assert meeting_participants(snapshot(), [segment(0, diarization_label="Speaker 1")])[0]["id"] != people[0]["id"]


def test_names_without_email_are_meeting_scoped_and_silent_attendees_have_no_profile():
    meeting = snapshot([{"name": "Silent", "email": "silent@example.com"}])
    people = meeting_participants(meeting, [segment(0, name="Alice")])
    assert len(people) == 1 and people[0]["display_name"] == "Alice"
    assert people[0]["identity_scope"] == "meeting"
    assert meeting_participants(snapshot(), [segment(0, name="Alice")])[0]["id"] != people[0]["id"]


def test_generic_speaker_name_and_equivalent_label_share_one_meeting_identity():
    people = meeting_participants(snapshot(), [segment(0, name="Speaker1"), segment(1, diarization_label="Speaker1")])
    assert len(people) == 1 and people[0]["segment_ids"] == ["segment-0", "segment-1"]
    assert people[0]["identity_scope"] == "meeting"
