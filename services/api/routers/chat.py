from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from services.api.routers.base import list_response
from services.chat.participants import chat_participants
from services.chat.service import (
    MAX_CONTEXT_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_TOPIC_LENGTH,
    ChatRoomClosedError,
    ChatRoomNotFoundError,
    create_room,
    delete_room,
    get_room,
    list_rooms,
    post_user_message,
    stop_agent_access,
    update_room,
)

log = logging.getLogger("graphs.chat")

router = APIRouter()


def _call(operation: Callable[..., Any], *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except ChatRoomNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ChatRoomClosedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class CreateRoomRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=MAX_TOPIC_LENGTH)
    context: str = Field(default="", max_length=MAX_CONTEXT_LENGTH)


class PostMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


@router.get("")
def list_all(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    rooms, total = list_rooms(limit=limit, offset=offset)
    return list_response(rooms, total)


@router.post("", status_code=201)
def create(body: CreateRoomRequest):
    return _call(create_room, body.topic, body.context)


@router.get("/config")
def config():
    return {"participants": _call(lambda: [p.name for p in chat_participants()])}


@router.get("/{room_id}")
def get_one(room_id: int, after_message_id: int = Query(0, ge=0)):
    return _call(get_room, room_id, after_message_id)


@router.patch("/{room_id}")
def update(room_id: int, body: CreateRoomRequest):
    return _call(update_room, room_id, body.topic, body.context)


@router.delete("/{room_id}", status_code=204)
def delete(room_id: int):
    _call(delete_room, room_id)


@router.post("/{room_id}/messages", status_code=201)
def post_message(room_id: int, body: PostMessageRequest, background_tasks: BackgroundTasks):
    # A misconfigured participant registry fails the request here, before the
    # message is stored — mentions are never silently disabled.
    participants = _call(chat_participants)
    message = _call(post_user_message, room_id, body.body)
    # Mentions trigger only from user-authored messages, so AI participants and
    # coding agents can never summon each other into a reply loop.
    for participant in participants:
        # (?<!\w) keeps emails like mail@kimi.example from reading as mentions.
        if re.search(rf"(?<!\w)@{re.escape(participant.name)}\b", body.body, re.IGNORECASE):
            background_tasks.add_task(_run_mentioned_reply, room_id, participant.name)
    return message


async def _run_mentioned_reply(room_id: int, participant: str) -> None:
    from services.graphs.runtime import dispatch

    try:
        await dispatch("chat", {"room_id": room_id, "participant": participant})
    except Exception:  # noqa: BLE001 - background task; surface via logs, never a 500
        log.exception(
            "chat: mention-triggered reply failed for %s in room %s", participant, room_id
        )


@router.post("/{room_id}/stop")
def stop(room_id: int):
    return _call(stop_agent_access, room_id)
