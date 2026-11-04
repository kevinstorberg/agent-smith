"""Chat graph tests with the LLM and chat service faked at module level.

Mirrors the improve-graph test approach: patch the module-level names the
graph imported (get_room, build_chat_model, post_graph_message) and drive the
real graph end-to-end through dispatch.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event

import pytest

from services.graphs.runtime import GraphContractError, dispatch, scan_library


class _FakeModel:
    def __init__(self, reply: str, calls: list):
        self._reply = reply
        self._calls = calls

    async def ainvoke(self, messages):
        self._calls.append(messages)

        class _Response:
            content = self._reply

        return _Response()


def _open_room(room_id: int = 42, topic: str = "Small design", context: str = "") -> dict:
    return {"id": room_id, "topic": topic, "context": context, "state": "open"}


def _message(message_id: int, author: str, body: str) -> dict:
    return {"id": message_id, "author": author, "body": body}


def _page(room: dict, messages: list[dict], has_more: bool = False) -> dict:
    return {
        "room": room,
        "messages": messages,
        "last_message_id": messages[-1]["id"] if messages else 0,
        "has_more": has_more,
    }


@pytest.fixture
def harness(monkeypatch):
    """Patch registry env + the chat module's service/LLM seams; capture calls."""
    from services.graphs.library import chat

    monkeypatch.delenv("CHAT_MODEL_IDS", raising=False)
    monkeypatch.setenv("CHAT_MODEL_NAMES", "Kimi,Qwen")
    monkeypatch.setenv("CHAT_KIMI_MODEL_ID", "us.moonshotai.kimi-k3")
    monkeypatch.setenv("CHAT_QWEN_MODEL_ID", "qwen.qwen3-max")

    captured: dict = {"model_calls": [], "model_roles": [], "posts": [], "reply": "A helpful reply."}
    pages = {"sequence": [_page(_open_room(), [_message(1, "user", "What do you think?")])]}

    def fake_get_room(room_id, after_message_id=0):
        return pages["sequence"].pop(0)

    def fake_build_chat_model(role, fallback_role=None):
        captured["model_roles"].append((role, fallback_role))
        return _FakeModel(captured["reply"], captured["model_calls"])

    def fake_post(room_id, author, body):
        captured["posts"].append((room_id, author, body))
        return _message(99, author, body)

    monkeypatch.setattr(chat, "get_room", fake_get_room)
    monkeypatch.setattr(chat, "build_chat_model", fake_build_chat_model)
    monkeypatch.setattr(chat, "post_graph_message", fake_post)
    captured["pages"] = pages
    return captured


def test_chat_graph_is_discovered_with_participant_schema():
    registry = scan_library()

    assert registry["chat"].INPUT_SCHEMA == {"room_id": "integer", "participant": "string"}


@pytest.mark.parametrize(
    "inputs", [{}, {"room_id": 42}, {"participant": "Kimi"}, {"room_id": 42, "participant": 7}]
)
def test_chat_graph_rejects_missing_or_wrong_inputs(inputs):
    with pytest.raises(ValueError, match="missing or wrong type"):
        asyncio.run(dispatch("chat", inputs))


def test_happy_path_posts_reply_as_registered_participant(harness):
    result = json.loads(asyncio.run(dispatch("chat", {"room_id": 42, "participant": "kimi"})))

    assert harness["model_roles"] == [("chat_kimi", "chat")]
    assert harness["posts"] == [(42, "Kimi", "A helpful reply.")]
    assert result["author"] == "Kimi"
    assert result["message"]["id"] == 99
    assert result["room"] == {"id": 42, "topic": "Small design", "state": "open"}
    assert result["transcript_truncated"] is False


def test_prompt_carries_room_material_and_persona(harness):
    harness["pages"]["sequence"] = [
        _page(
            _open_room(topic="Index strategy", context="Prefer small changes."),
            [_message(1, "user", "Thoughts?"), _message(2, "codex", "I would extend it.")],
        )
    ]

    asyncio.run(dispatch("chat", {"room_id": 42, "participant": "Qwen"}))

    system, human = harness["model_calls"][0]
    assert "You are Qwen" in system.content
    assert "Kimi" in system.content  # other registered participants are named
    assert "GROUNDING (critical)" in system.content
    assert "Topic: Index strategy" in human.content
    assert "Context: Prefer small changes." in human.content
    assert "user: Thoughts?" in human.content
    assert "codex: I would extend it." in human.content


def test_unknown_participant_fails_before_any_read_or_model_call(harness):
    with pytest.raises(ValueError, match="unknown chat participant.*Kimi, Qwen"):
        asyncio.run(dispatch("chat", {"room_id": 42, "participant": "Bard"}))

    assert harness["model_calls"] == []
    assert harness["posts"] == []


def test_closed_room_fails_without_model_spend(harness):
    closed = dict(_open_room(), state="closed")
    harness["pages"]["sequence"] = [_page(closed, [])]

    with pytest.raises(GraphContractError, match="closed"):
        asyncio.run(dispatch("chat", {"room_id": 42, "participant": "Kimi"}))

    assert harness["model_calls"] == []
    assert harness["posts"] == []


def test_empty_model_output_is_never_posted(harness):
    harness["reply"] = "   \n  "

    with pytest.raises(GraphContractError, match="empty reply"):
        asyncio.run(dispatch("chat", {"room_id": 42, "participant": "Kimi"}))

    assert harness["posts"] == []


def test_oversize_reply_is_rejected_and_never_posted(harness):
    harness["reply"] = ("word " * 2200).strip()  # ~11,000 chars

    with pytest.raises(GraphContractError, match="6000 characters or fewer"):
        asyncio.run(dispatch("chat", {"room_id": 42, "participant": "Kimi"}))

    assert harness["posts"] == []


def test_paging_spans_pages_and_keeps_the_whole_transcript(harness):
    room = _open_room()
    first = [_message(i, "user", f"m{i}") for i in range(1, 101)]
    second = [_message(i, "user", f"m{i}") for i in range(101, 251)]
    harness["pages"]["sequence"] = [_page(room, first, has_more=True), _page(room, second)]

    result = json.loads(asyncio.run(dispatch("chat", {"room_id": 42, "participant": "Kimi"})))

    _, human = harness["model_calls"][0]
    assert "user: m1\n\n" in human.content
    assert "user: m50\n\n" in human.content
    assert "user: m250" in human.content
    assert "earlier messages were omitted" not in human.content
    assert result["transcript_truncated"] is False


def test_more_than_fifty_native_pages_and_a_concurrent_append_reach_the_model(harness, monkeypatch):
    from services.chat.service import create_room, delete_room, get_room, post_user_message
    from services.db import get_connection
    from services.graphs.library import chat

    room = create_room("Complete conversation", "Keep the entire conversation.")
    first_page = Event()
    appended = Event()
    cursors = []
    try:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("""INSERT INTO chat_messages (room_id, author, body)
                SELECT %s, 'user', 'complete-message-' || number::text
                FROM generate_series(1, 5105) AS number""", (room["id"],))

        def read_page(room_id, after_message_id=0):
            page = get_room(room_id, after_message_id)
            cursors.append(after_message_id)
            if after_message_id == 0:
                first_page.set()
                assert appended.wait(5)
            return page

        def append_message():
            assert first_page.wait(5)
            try:
                return post_user_message(room["id"], "APPENDED_AFTER_FIRST_PAGE")
            finally:
                appended.set()

        monkeypatch.setattr(chat, "get_room", read_page)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(append_message)
            try:
                result = json.loads(asyncio.run(dispatch("chat", {"room_id": room["id"], "participant": "Kimi"})))
            finally:
                appended.set()
            future.result(timeout=5)

        assert len(harness["model_calls"]) == 1
        _, human = harness["model_calls"][0]
        assert human.content.count("user: complete-message-") == 5105
        for number in (1, 200, 201, 5001, 5105):
            assert f"user: complete-message-{number}\n\n" in human.content
        assert human.content.endswith("user: APPENDED_AFTER_FIRST_PAGE")
        assert len(cursors) == 52 and cursors[0] == 0
        assert all(left < right for left, right in zip(cursors, cursors[1:]))
        assert result["transcript_truncated"] is False
    finally:
        delete_room(room["id"])


@pytest.mark.parametrize("pages", [
    [_page(_open_room(), [], has_more=True)],
    [_page(_open_room(), [_message(2, "user", "second"), _message(1, "user", "first")])],
    [_page(_open_room(), [_message(1, "user", "first")], has_more=True),
     _page(_open_room(), [_message(1, "user", "repeated")])],
    [{**_page(_open_room(), [_message(1, "user", "first")]), "last_message_id": 2}],
    [{**_page(_open_room(), []), "last_message_id": False}],
    [{**_page(_open_room(), []), "has_more": "yes"}],
    [_page(_open_room(room_id=43), [])],
    [_page(_open_room(), [_message(1, "user", "first")], has_more=True),
     _page({**_open_room(), "state": "closed"}, [_message(2, "user", "second")])],
])
def test_incomplete_or_inconsistent_transcript_never_reaches_model(harness, pages):
    harness["pages"]["sequence"] = pages

    with pytest.raises(GraphContractError):
        asyncio.run(dispatch("chat", {"room_id": 42, "participant": "Kimi"}))

    assert harness["model_calls"] == harness["model_roles"] == harness["posts"] == []


def test_transcript_deadline_aborts_before_any_partial_model_request(harness, monkeypatch):
    from services.graphs.library import chat

    release = Event()
    reads = []

    def read_page(room_id, after_message_id=0):
        reads.append(after_message_id)
        if after_message_id == 0:
            return _page(_open_room(), [_message(1, "user", "Partial source")], has_more=True)
        assert release.wait(5)
        return _page(_open_room(), [_message(2, "user", "Late source")])

    assert chat._TRANSCRIPT_READ_SECONDS == 30
    monkeypatch.setattr(chat, "_TRANSCRIPT_READ_SECONDS", 0.05)
    monkeypatch.setattr(chat, "get_room", read_page)

    async def run():
        try:
            with pytest.raises(GraphContractError, match="deadline"):
                await dispatch("chat", {"room_id": 42, "participant": "Kimi"})
        finally:
            release.set()

    asyncio.run(run())
    assert reads
    assert harness["model_calls"] == harness["model_roles"] == harness["posts"] == []
