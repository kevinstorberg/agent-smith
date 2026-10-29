from uuid import uuid4

import pytest

from services.meetings.participants import email_participant, meeting_participants, speaker_key


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


def test_email_participant_matches_meeting_identity_and_normalizes_display_name():
    direct = email_participant(" Alice+Meetings@Example.com ", " Alice ")
    inferred = meeting_participants(snapshot(), [segment(0, email="alice+meetings@example.com", name="Alice")])[0]
    assert inferred == {**direct, "segment_ids": ["segment-0"], "identity_source": "speaker_email"}
    assert email_participant("alice+meetings@example.com")["display_name"] == "alice+meetings@example.com"


@pytest.mark.parametrize("email", [None, "", "bad-address", "name @example.test", "<name@example.test>"])
def test_email_participant_rejects_unusable_identity(email):
    with pytest.raises(ValueError, match="Participant email"):
        email_participant(email)


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


def test_speaker_key_normalizes_whitespace_and_email_but_preserves_provider_labels():
    speaker = {"name": " Me ", "email": " Alice@Example.test ", "diarization_label": " Speaker 1 ", "source": " system "}
    normalized = {"name": "Me", "email": "alice@example.test", "diarization_label": "Speaker 1", "source": "system"}
    assert speaker_key(speaker) == speaker_key(normalized)
    assert len(speaker_key(speaker)) == 64
    assert speaker_key(normalized) != speaker_key({**normalized, "diarization_label": "speaker 1"})


def test_explicit_manual_speaker_mapping_identifies_me_and_them_without_roster_guessing():
    segments = [segment(0, name="Me", source="microphone"), segment(1, name="Them", source="system")]
    profile_id = str(uuid4())
    meeting = {**snapshot(), "manual_participants": [
        {"name": "Alice", "email": "alice@example.test", "speaker_key": speaker_key(segments[0]["speaker"])},
        {"name": "Bob", "profile_id": profile_id, "speaker_key": speaker_key(segments[1]["speaker"])},
    ]}
    alice, bob = meeting_participants(meeting, segments)
    assert alice["id"] == email_participant("alice@example.test")["id"] and alice["segment_ids"] == ["segment-0"]
    assert bob["id"] == profile_id and bob["identity_key"] == f"profile:{profile_id}" and bob["segment_ids"] == ["segment-1"]


def test_manual_roster_matches_only_unambiguous_named_speakers_and_never_silent_attendees():
    meeting = {**snapshot(), "manual_participants": [
        {"name": " Alice ", "email": "alice@example.test"},
        {"name": "Silent", "email": "silent@example.test"},
    ]}
    people = meeting_participants(meeting, [segment(0, name="ALICE"), segment(1, name="Me", diarization_label="Speaker 1")])
    assert people[0]["email"] == "alice@example.test" and people[0]["segment_ids"] == ["segment-0"]
    assert people[1]["email"] is None and people[1]["identity_scope"] == "meeting"
    assert len(people) == 2


def test_manual_roster_does_not_guess_between_conflicting_named_identities():
    meeting = {**snapshot([{"name": "Alex", "email": "first@example.test"}]), "manual_participants": [
        {"name": "Alex", "email": "second@example.test"},
    ]}
    person = meeting_participants(meeting, [segment(0, name="Alex")])[0]
    assert person["identity_scope"] == "meeting" and person["email"] is None


def test_explicit_name_only_mapping_can_identify_an_unlabeled_microphone_for_this_meeting():
    segments = [segment(0, source="microphone"), segment(1, source="microphone")]
    meeting = {**snapshot(), "manual_participants": [{"name": "Alice", "speaker_key": speaker_key(segments[0]["speaker"])}]}
    person = meeting_participants(meeting, segments)[0]
    assert person["display_name"] == "Alice" and person["identity_scope"] == "meeting"
    assert person["segment_ids"] == ["segment-0", "segment-1"]


@pytest.mark.parametrize("entry", [
    {"name": "Alice", "email": "invalid"},
    {"name": "Alice", "profile_id": "invalid"},
    {"name": "Alice", "speaker_key": "unknown"},
    {"name": "Alice", "speaker_key": "0" * 64},
])
def test_manual_mapping_rejects_invalid_or_dangling_explicit_identities(entry):
    with pytest.raises(ValueError):
        meeting_participants({**snapshot(), "manual_participants": [entry]}, [segment(0, name="Alice")])


def test_manual_mapping_cannot_assign_the_same_speaker_twice():
    segments = [segment(0, name="Me")]
    key = speaker_key(segments[0]["speaker"])
    meeting = {**snapshot(), "manual_participants": [{"name": name, "speaker_key": key} for name in ("Alice", "Bob")]}
    with pytest.raises(ValueError, match="multiple manual participants"):
        meeting_participants(meeting, segments)
