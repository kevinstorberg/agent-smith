from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from psycopg2.extras import RealDictCursor

from scripts.shared.agents import AGENT_TARGETS
from services.chat.participants import find_participant
from services.db import get_connection

MAX_TOPIC_LENGTH = 200
MAX_CONTEXT_LENGTH = 20_000
MAX_MESSAGE_LENGTH = 8_000
MAX_WAIT_SECONDS = 20
MESSAGE_PAGE_SIZE = 100
READ_POLL_INTERVAL_SECONDS = 1.0


class ChatRoomNotFoundError(LookupError):
    pass


class ChatRoomClosedError(RuntimeError):
    pass


def _positive_id(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _non_negative_id(value: int, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _bounded_text(value: str, field: str, maximum: int, *, required: bool) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError(f"{field} must not be empty")
    if len(cleaned) > maximum:
        raise ValueError(f"{field} must be {maximum} characters or fewer")
    return cleaned


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for field in ("created_at", "updated_at", "closed_at"):
        value = result.get(field)
        if isinstance(value, datetime):
            result[field] = value.isoformat()
    return result


def _room_view(row: dict[str, Any]) -> dict[str, Any]:
    room = _serialize(row)
    room["state"] = "closed" if room.get("closed_at") else "open"
    return room


def create_room(topic: str, context: str = "") -> dict[str, Any]:
    clean_topic = _bounded_text(topic, "topic", MAX_TOPIC_LENGTH, required=True)
    clean_context = _bounded_text(context, "context", MAX_CONTEXT_LENGTH, required=False)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO chat_rooms (topic, context)
                VALUES (%s, %s)
                RETURNING *
                """,
                (clean_topic, clean_context),
            )
            room = cur.fetchone()
    assert room and room["id"] > 0, "chat room insert returned no id"
    return _room_view(dict(room))


def list_rooms(limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    _non_negative_id(offset, "offset")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS count FROM chat_rooms")
            total = cur.fetchone()["count"]
            cur.execute(
                """
                SELECT * FROM chat_rooms
                ORDER BY updated_at DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rooms = [_room_view(dict(row)) for row in cur.fetchall()]
    return rooms, total


def _require_room(cur, room_id: int) -> dict[str, Any]:
    cur.execute("SELECT * FROM chat_rooms WHERE id = %s", (room_id,))
    row = cur.fetchone()
    if not row:
        raise ChatRoomNotFoundError(f"Chat room not found: {room_id}")
    return dict(row)


def _message_page(cur, room_id: int, after_message_id: int) -> tuple[list[dict[str, Any]], bool]:
    cur.execute(
        """
        SELECT * FROM chat_messages
        WHERE room_id = %s AND id > %s
        ORDER BY id
        LIMIT %s
        """,
        (room_id, after_message_id, MESSAGE_PAGE_SIZE + 1),
    )
    rows = [dict(row) for row in cur.fetchall()]
    has_more = len(rows) > MESSAGE_PAGE_SIZE
    return [_serialize(row) for row in rows[:MESSAGE_PAGE_SIZE]], has_more


def get_room(room_id: int, after_message_id: int = 0) -> dict[str, Any]:
    _positive_id(room_id, "room_id")
    _non_negative_id(after_message_id, "after_message_id")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            room = _require_room(cur, room_id)
            messages, has_more = _message_page(cur, room_id, after_message_id)
    last_message_id = messages[-1]["id"] if messages else after_message_id
    return {
        "room": _room_view(room),
        "messages": messages,
        "last_message_id": last_message_id,
        "has_more": has_more,
    }


def _post_message(room_id: int, author: str, body: str) -> dict[str, Any]:
    _positive_id(room_id, "room_id")
    clean_body = _bounded_text(body, "body", MAX_MESSAGE_LENGTH, required=True)
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM chat_rooms
                WHERE id = %s
                FOR UPDATE
                """,
                (room_id,),
            )
            room = cur.fetchone()
            if not room:
                raise ChatRoomNotFoundError(f"Chat room not found: {room_id}")
            if room["closed_at"] is not None:
                raise ChatRoomClosedError(f"Chat room {room_id} is closed")
            cur.execute(
                """
                INSERT INTO chat_messages (room_id, author, body)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                (room_id, author, clean_body),
            )
            message = cur.fetchone()
            cur.execute("UPDATE chat_rooms SET updated_at = now() WHERE id = %s", (room_id,))
    result = _serialize(dict(message))
    assert result["id"] > 0 and result["room_id"] == room_id, "chat message insert failed"
    return result


def post_user_message(room_id: int, body: str) -> dict[str, Any]:
    return _post_message(room_id, "user", body)


def post_agent_message(room_id: int, agent: str, body: str) -> dict[str, Any]:
    if agent not in AGENT_TARGETS:
        raise ValueError(
            f"agent must be one of {', '.join(sorted(AGENT_TARGETS))}; got {agent!r}"
        )
    return _post_message(room_id, agent, body)


def post_graph_message(room_id: int, author: str, body: str) -> dict[str, Any]:
    # AI participants may only post under a name registered in the participant
    # registry, which already rejects reserved identities (user/claude/codex/
    # gemini). The MCP chat_post surface (post_agent_message) stays the only
    # path for real coding-agent authors.
    participant = find_participant(author)
    return _post_message(room_id, participant.name, body)


def stop_agent_access(room_id: int) -> dict[str, Any]:
    _positive_id(room_id, "room_id")
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE chat_rooms
                SET closed_at = COALESCE(closed_at, now()),
                    updated_at = CASE WHEN closed_at IS NULL THEN now() ELSE updated_at END
                WHERE id = %s
                RETURNING *
                """,
                (room_id,),
            )
            room = cur.fetchone()
    if not room:
        raise ChatRoomNotFoundError(f"Chat room not found: {room_id}")
    result = _room_view(dict(room))
    assert result["closed_at"] and result["state"] == "closed", "chat room stop failed"
    return result


def _agent_snapshot(room_id: int, after_message_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            room = _require_room(cur, room_id)
            room_view = _room_view(room)
            if room_view["state"] == "closed":
                return {
                    "room": room_view,
                    "messages": [],
                    "last_message_id": after_message_id,
                    "has_more": False,
                    "outcome": "closed",
                }
            messages, has_more = _message_page(cur, room_id, after_message_id)
    return {
        "room": room_view,
        "messages": messages,
        "last_message_id": messages[-1]["id"] if messages else after_message_id,
        "has_more": has_more,
        "outcome": "messages" if messages else "snapshot",
    }


async def read_agent_room(
    room_id: int,
    after_message_id: int = 0,
    wait_seconds: int = 0,
    *,
    poll_interval: float = READ_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    _positive_id(room_id, "room_id")
    _non_negative_id(after_message_id, "after_message_id")
    if isinstance(wait_seconds, bool) or not isinstance(wait_seconds, int):
        raise ValueError("wait_seconds must be an integer")
    if not 0 <= wait_seconds <= MAX_WAIT_SECONDS:
        raise ValueError(f"wait_seconds must be between 0 and {MAX_WAIT_SECONDS}")
    if poll_interval < 0:
        raise ValueError("poll_interval must be non-negative")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    while True:
        result = await asyncio.to_thread(_agent_snapshot, room_id, after_message_id)
        if result["outcome"] in {"messages", "closed"} or wait_seconds == 0:
            return result

        remaining = deadline - loop.time()
        if remaining <= 0:
            result["outcome"] = "timeout"
            result["wait_seconds"] = wait_seconds
            return result
        await asyncio.sleep(min(poll_interval, remaining))
