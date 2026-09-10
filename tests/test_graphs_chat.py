"""Chat graph tests with the LLM and chat service faked at module level.

Mirrors the improve-graph test approach: patch the module-level names the
graph imported (get_room, build_chat_model, post_graph_message) and drive the
real graph end-to-end through dispatch.
"""
from __future__ import annotations

import asyncio
import json

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

    monkeypatch.setenv("CHAT_MODEL_NAMES", "Kimi,Qwen")
    monkeypatch.setenv("CHAT_MODEL_IDS", "moonshotai.kimi-k2.5,qwen.qwen3-max")

    captured: dict = {"model_calls": [], "model_ids": [], "posts": [], "reply": "A helpful reply."}
    pages = {"sequence": [_page(_open_room(), [_message(1, "user", "What do you think?")])]}

    def fake_get_room(room_id, after_message_id=0):
        return pages["sequence"].pop(0)

    def fake_build_chat_model(role, fallback_role=None, *, model_id=None):
        assert role == "chat"
        captured["model_ids"].append(model_id)
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

    assert harness["model_ids"] == ["moonshotai.kimi-k2.5"]
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


def test_paging_spans_pages_and_caps_transcript_to_the_tail(harness):
    room = _open_room()
    first = [_message(i, "user", f"m{i}") for i in range(1, 101)]
    second = [_message(i, "user", f"m{i}") for i in range(101, 251)]
    harness["pages"]["sequence"] = [_page(room, first, has_more=True), _page(room, second)]

    result = json.loads(asyncio.run(dispatch("chat", {"room_id": 42, "participant": "Kimi"})))

    _, human = harness["model_calls"][0]
    assert "m250" in human.content  # tail retained
    assert "m50: " not in human.content and "user: m50" not in human.content  # head dropped
    assert result["transcript_truncated"] is True
