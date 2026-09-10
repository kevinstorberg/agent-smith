from __future__ import annotations

import asyncio
import json

import pytest

from services.graphs.runtime import dispatch, scan_library


def test_chat_graph_is_discovered_with_room_id_schema():
    registry = scan_library()

    assert registry["chat"].INPUT_SCHEMA == {"room_id": "integer"}


def test_chat_graph_returns_shared_service_snapshot(monkeypatch):
    from services.graphs.library import chat

    expected = {
        "room": {"id": 42, "topic": "Small design", "state": "open"},
        "messages": [],
        "last_message_id": 0,
        "has_more": False,
    }
    monkeypatch.setattr(chat, "snapshot", lambda room_id: expected if room_id == 42 else None)

    result = asyncio.run(dispatch("chat", {"room_id": 42}))

    assert json.loads(result) == expected


def test_chat_graph_rejects_missing_room_id():
    with pytest.raises(ValueError, match="input 'room_id' missing or wrong type"):
        asyncio.run(dispatch("chat", {}))
