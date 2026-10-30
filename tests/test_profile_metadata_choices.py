import pytest
from psycopg2.extras import Json

from services.db import get_connection
from services.meetings import profile_db
from services.meetings.outputs import ProfileMetadataPatch
from tests.test_profile_management import extra_profiles as extra_profiles
from tests.test_profiles_router import client as client


def test_metadata_options_are_static_and_available_before_uuid_routes(client, monkeypatch):
    def unexpected_read(*args, **kwargs):
        raise AssertionError("Static choices must not read profiles")

    monkeypatch.setattr(profile_db, "get_profile", unexpected_read)
    response = client.get("/api/profiles/metadata-options")
    assert response.status_code == 200
    assert response.json()["gender"] == ["Male", "Female", "Non-binary", "Other"]
    assert "Single" in response.json()["marital_status"] and "Married" in response.json()["marital_status"]
    assert client.get("/api/meetings/profiles/metadata-options").json() == response.json()


def test_human_choices_normalize_and_clear_with_existing_revision_and_ownership(client, extra_profiles):
    profile = extra_profiles()
    path = f"/api/profiles/{profile['id']}"
    selected = client.patch(path, json={"expected_revision": profile["revision"],
                                       "metadata": {"gender": " female ", "marital_status": "MARRIED"}})
    assert selected.status_code == 200
    current = selected.json()
    assert current["metadata"] == {"gender": "Female", "marital_status": "Married"}
    assert current["metadata_provenance"] == {"gender": {"human": True}, "marital_status": {"human": True}}
    assert client.patch(path, json={"expected_revision": profile["revision"], "metadata": {"gender": "Male"}}).status_code == 409
    cleared = client.patch(path, json={"expected_revision": current["revision"], "metadata": {"gender": ""}}).json()
    assert cleared["metadata"] == {"marital_status": "Married"}
    assert cleared["metadata_provenance"]["gender"] == {"human": True}


@pytest.mark.parametrize("field", ["gender", "marital_status"])
def test_unknown_new_choice_fails_without_any_profile_write(client, extra_profiles, field):
    profile = extra_profiles()
    response = client.patch(f"/api/profiles/{profile['id']}", json={
        "expected_revision": profile["revision"], "metadata": {field: "Unsupported new value", "company": "Must not save"},
    })
    assert response.status_code == 422 and field in response.json()["detail"]
    unchanged = profile_db.get_profile(profile["id"])
    assert unchanged["metadata"] == {} and unchanged["revision"] == profile["revision"]


def test_legacy_choice_remains_visible_and_only_exact_current_value_can_be_retained(client, extra_profiles):
    profile = extra_profiles()
    legacy = "  Existing custom value  "
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE participant_profiles SET metadata=%s WHERE id=%s", (Json({"gender": legacy}), profile["id"]))
    path = f"/api/profiles/{profile['id']}"
    assert client.get(path).json()["metadata"]["gender"] == legacy
    retained = client.patch(path, json={"expected_revision": profile["revision"], "metadata": {"gender": legacy, "company": "New company"}})
    assert retained.status_code == 200 and retained.json()["metadata"]["gender"] == legacy
    current = retained.json()
    assert client.patch(path, json={"expected_revision": current["revision"], "metadata": {"gender": legacy.strip()}}).status_code == 422
    selected = client.patch(path, json={"expected_revision": current["revision"], "metadata": {"gender": "Male"}}).json()
    assert selected["metadata"]["gender"] == "Male"
    assert client.patch(path, json={"expected_revision": current["revision"], "metadata": {"gender": legacy}}).status_code == 409
    assert client.patch(path, json={"expected_revision": selected["revision"], "metadata": {"gender": legacy}}).status_code == 422


def test_agent_uses_same_choices_and_cannot_introduce_legacy_or_blank_values():
    evidence = [{"segment_id": "segment-0", "quote": "I am married."}]
    patch = ProfileMetadataPatch(subject_id="person", fields={"marital_status": " married "}, evidence=evidence)
    assert patch.fields == {"marital_status": "Married"}
    for invalid in ("Previously custom", ""):
        with pytest.raises(ValueError):
            ProfileMetadataPatch(subject_id="person", fields={"marital_status": invalid}, evidence=evidence)
