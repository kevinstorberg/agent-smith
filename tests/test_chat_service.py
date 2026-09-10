from __future__ import annotations

import asyncio

import pytest

from services.chat.service import (
    ChatRoomClosedError,
    ChatRoomNotFoundError,
    create_room,
    get_room,
    list_rooms,
    post_agent_message,
    post_user_message,
    read_agent_room,
    stop_agent_access,
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


def test_room_and_cursor_round_trip():
    room = create_room("Pick an indexing strategy", "Prefer the smallest safe change.")
    first = post_user_message(room["id"], "What would you change?")
    second = post_agent_message(room["id"], "codex", "I would extend the current index.")

    result = get_room(room["id"], after_message_id=first["id"])

    assert result["room"]["state"] == "open"
    assert [message["id"] for message in result["messages"]] == [second["id"]]
    assert result["last_message_id"] == second["id"]
    assert result["has_more"] is False


def test_list_rooms_reports_total_and_newest_activity_first():
    first = create_room("First")
    second = create_room("Second")
    post_user_message(first["id"], "Bump the older room")

    rooms, total = list_rooms()

    assert total == 2
    assert [room["id"] for room in rooms] == [first["id"], second["id"]]


def test_stop_is_irreversible_and_rejects_new_messages():
    room = create_room("Stop semantics")

    stopped = stop_agent_access(room["id"])
    stopped_again = stop_agent_access(room["id"])

    assert stopped["state"] == "closed"
    assert stopped_again["closed_at"] == stopped["closed_at"]
    with pytest.raises(ChatRoomClosedError, match="closed"):
        post_agent_message(room["id"], "claude", "This must not be stored")
    with pytest.raises(ChatRoomClosedError, match="closed"):
        post_user_message(room["id"], "Neither should this")
    assert get_room(room["id"])["messages"] == []


def test_agent_read_returns_messages_then_terminal_closed_state():
    room = create_room("Agent polling")
    message = post_user_message(room["id"], "Please review this.")

    available = asyncio.run(read_agent_room(room["id"], wait_seconds=0))
    assert available["outcome"] == "messages"
    assert available["last_message_id"] == message["id"]

    stop_agent_access(room["id"])
    closed = asyncio.run(read_agent_room(room["id"], message["id"], wait_seconds=0))
    assert closed["outcome"] == "closed"
    assert closed["messages"] == []


def test_agent_read_times_out_with_bounded_wait(monkeypatch):
    room = create_room("Quiet room")
    clock = iter((0.0, 0.0, 1.0))

    class FakeLoop:
        def time(self):
            return next(clock)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    result = asyncio.run(read_agent_room(room["id"], wait_seconds=1))

    assert result["outcome"] == "timeout"
    assert result["wait_seconds"] == 1


@pytest.mark.parametrize("agent", ["user", "opinion", "unknown"])
def test_agent_post_rejects_unknown_or_impersonated_agent(agent):
    room = create_room("Identity boundary")
    with pytest.raises(ValueError, match="agent must be one of"):
        post_agent_message(room["id"], agent, "Hello")


def test_missing_room_fails_clearly():
    with pytest.raises(ChatRoomNotFoundError, match="Chat room not found"):
        get_room(2_000_000_000)


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda: create_room("   "), "topic must not be empty"),
        (lambda: get_room(0), "room_id must be a positive integer"),
        (
            lambda: asyncio.run(read_agent_room(1, wait_seconds=21)),
            "wait_seconds must be between 0 and 20",
        ),
    ],
)
def test_boundary_validation(operation, message):
    with pytest.raises(ValueError, match=message):
        operation()
