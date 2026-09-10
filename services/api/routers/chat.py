from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.api.routers.base import list_response
from services.chat.service import (
    MAX_CONTEXT_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_TOPIC_LENGTH,
    ChatRoomClosedError,
    ChatRoomNotFoundError,
    create_room,
    get_room,
    list_rooms,
    post_user_message,
    stop_agent_access,
)

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


@router.get("/{room_id}")
def get_one(room_id: int, after_message_id: int = Query(0, ge=0)):
    return _call(get_room, room_id, after_message_id)


@router.post("/{room_id}/messages", status_code=201)
def post_message(room_id: int, body: PostMessageRequest):
    return _call(post_user_message, room_id, body.body)


@router.post("/{room_id}/stop")
def stop(room_id: int):
    return _call(stop_agent_access, room_id)
