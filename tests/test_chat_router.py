from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.api.routers.chat import (
    CreateRoomRequest,
    PostMessageRequest,
    create,
    get_one,
    list_all,
    post_message,
    stop,
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


def test_user_rest_flow_never_accepts_an_author():
    room = create(CreateRoomRequest(topic="REST flow", context="Use the real sessions."))
    message = post_message(room["id"], PostMessageRequest(body="Start here"))

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
        post_message(room["id"], PostMessageRequest(body="Too late"))
    assert closed.value.status_code == 409


def test_rest_maps_whitespace_only_input_to_validation_error():
    with pytest.raises(HTTPException) as invalid:
        create(CreateRoomRequest(topic="   "))
    assert invalid.value.status_code == 422
