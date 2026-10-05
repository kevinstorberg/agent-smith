from __future__ import annotations

import pytest
from fastapi import BackgroundTasks, HTTPException

from services.api.routers.chat import (
    CreateRoomRequest,
    PostMessageRequest,
    config,
    create,
    delete,
    get_one,
    list_all,
    post_message,
    stop,
    update,
)
from services.db import get_connection


@pytest.fixture(autouse=True)
def _clean_chat_rooms():
    def clean() -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chat_rooms")

    clean()
    yield
    clean()


def _post(room_id: int, body: str) -> tuple[dict, BackgroundTasks]:
    tasks = BackgroundTasks()
    message = post_message(room_id, PostMessageRequest(body=body), tasks)
    return message, tasks


def _scheduled_participants(tasks: BackgroundTasks) -> list[str]:
    return [task.args[1] for task in tasks.tasks]


def test_user_rest_flow_never_accepts_an_author():
    room = create(CreateRoomRequest(topic="REST flow", context="Use the real sessions."))
    message, _ = _post(room["id"], "Start here")

    result = get_one(room["id"], after_message_id=0)

    assert message["author"] == "user"
    assert result["messages"] == [message]
    assert list_all(limit=50, offset=0)["total"] == 1


def test_rest_maps_missing_and_closed_rooms():
    with pytest.raises(HTTPException) as missing:
        get_one(2_000_000_000, after_message_id=0)
    assert missing.value.status_code == 404

    room = create(CreateRoomRequest(topic="Close me"))
    stop(room["id"])
    with pytest.raises(HTTPException) as closed:
        _post(room["id"], "Too late")
    assert closed.value.status_code == 409


def test_rest_updates_and_deletes_rooms():
    room = create(CreateRoomRequest(topic="Before", context="Old"))

    updated = update(room["id"], CreateRoomRequest(topic="After", context="New"))
    assert updated["topic"] == "After"
    assert updated["context"] == "New"

    delete(room["id"])
    with pytest.raises(HTTPException) as missing:
        get_one(room["id"], after_message_id=0)
    assert missing.value.status_code == 404


def test_rest_maps_update_and_delete_of_missing_room_to_404():
    with pytest.raises(HTTPException) as update_missing:
        update(2_000_000_000, CreateRoomRequest(topic="Anything"))
    assert update_missing.value.status_code == 404

    with pytest.raises(HTTPException) as delete_missing:
        delete(2_000_000_000)
    assert delete_missing.value.status_code == 404


def test_rest_maps_whitespace_only_input_to_validation_error():
    with pytest.raises(HTTPException) as invalid:
        create(CreateRoomRequest(topic="   "))
    assert invalid.value.status_code == 422


@pytest.fixture
def _participants_env(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL_NAMES", "Kimi,Qwen")
    monkeypatch.setenv("CHAT_MODEL_IDS", "moonshotai.kimi-k2.5,qwen.qwen3-max")


@pytest.mark.parametrize("mention", ["@kimi", "@Kimi", "@KIMI"])
def test_mention_matching_is_case_insensitive(_participants_env, mention):
    room = create(CreateRoomRequest(topic="Summon"))

    _, tasks = _post(room["id"], f"hey {mention}, thoughts?")

    assert _scheduled_participants(tasks) == ["Kimi"]


def test_each_distinct_mentioned_participant_is_scheduled_once(_participants_env):
    room = create(CreateRoomRequest(topic="Summon several"))

    _, tasks = _post(room["id"], "@Kimi @qwen @kimi weigh in please")

    assert _scheduled_participants(tasks) == ["Kimi", "Qwen"]


@pytest.mark.parametrize("body", ["no mention here", "@KimiX is not registered", "mail@kimi.example is an email, not a mention"])
def test_non_mentions_schedule_nothing(_participants_env, body):
    room = create(CreateRoomRequest(topic="Quiet"))

    _, tasks = _post(room["id"], body)

    assert tasks.tasks == []


def test_misconfigured_registry_fails_the_post_before_storing_anything(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL_NAMES", "Kimi")
    monkeypatch.setenv("CHAT_MODEL_IDS", "id-one,id-two")
    room = create(CreateRoomRequest(topic="Broken registry"))

    with pytest.raises(HTTPException) as failure:
        _post(room["id"], "@Kimi hello")

    assert failure.value.status_code == 422
    assert "equal length" in failure.value.detail
    assert get_one(room["id"], after_message_id=0)["messages"] == []


def test_config_lists_participants_in_registry_order(_participants_env):
    assert config() == {"participants": ["Kimi", "Qwen"]}

