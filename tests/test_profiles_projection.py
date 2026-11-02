from uuid import uuid4

import pytest

from services.action_items import server as action_server
from services.profiles import server


def test_profile_discovery_caps_alias_emails_without_mutating_identity_or_exposing_evidence():
    emails = [f"person-{index}@example.test" for index in range(25)]
    profile = {"id": str(uuid4()), "display_name": "A person", "email": emails[-1], "emails": emails,
               "claims": [{"content": "Private evidence"}], "merge_history": ["history"]}
    result = server._identity(profile)
    assert result["emails"] == emails[:20]
    assert result["emails_omitted"] == 5
    assert result["email"] == emails[-1]
    assert "claims" not in result and "merge_history" not in result
    assert profile["emails"] == emails


@pytest.mark.parametrize("tags", [False, "", {}, 0])
def test_native_topic_functions_reject_invalid_falsy_tags_before_accessing_a_queue(monkeypatch, tags):
    def unexpected_queue(*args, **kwargs):
        raise AssertionError("Invalid tags reached storage")

    monkeypatch.setattr(server.db, "profile_queue", unexpected_queue)
    owner = str(uuid4())
    for operation in (lambda: server.profile_topic_list(owner, tags=tags),
                      lambda: server.profile_topic_create(owner, "Topic", tags=tags)):
        with pytest.raises(ValueError, match="tags"):
            operation()


@pytest.mark.parametrize("tags", [False, "", {}, 0])
def test_native_global_functions_reject_invalid_falsy_tags(monkeypatch, tags):
    def unexpected_cursor(*args, **kwargs):
        raise AssertionError("Invalid tags reached storage")

    monkeypatch.setattr(action_server.db, "_cursor", unexpected_cursor)
    for operation in (lambda: action_server.action_item_list(tags=tags),
                      lambda: action_server.action_item_create("Task", tags=tags)):
        with pytest.raises(ValueError, match="tags"):
            operation()
