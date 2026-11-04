"""Chat: posts one AI reply into a Chat Room as a named chat participant."""
from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from scripts.shared.agents import AGENT_TARGETS
from services.chat.participants import CHAT_MODEL_ROLE, chat_participants, find_participant
from services.chat.service import get_room, post_graph_message
from services.graphs.messages import extract_text
from services.graphs.model_factory import build_chat_model
from services.graphs.prompts import grounding_block

INPUT_SCHEMA = {"room_id": "integer", "participant": "string"}

_TRANSCRIPT_READ_SECONDS = 30
_MAX_REPLY_CHARS = 6_000

# Harness rules are deliberately NOT injected here: the rules assigned to the
# "opinion" virtual agent are plan-critique principles, the wrong register for
# a conversational reply. Chat-specific steering would be a new virtual agent.


class State(TypedDict):
    room_id: int
    participant: str
    model_role: str
    room: dict[str, Any]
    transcript: list[dict[str, Any]]
    draft: str
    result: dict[str, Any]


def _system_prompt(name: str, others: list[str]) -> str:
    coding_agents = ", ".join(f"'{agent}'" for agent in sorted(AGENT_TARGETS))
    company = f" and possibly other AI participants ({', '.join(others)})" if others else ""
    return (
        f"You are {name}, an AI participant in a shared chat room used by a human "
        f"('user'), coding agents ({coding_agents}),{company}. You post "
        "one reply per invocation, only when explicitly mentioned.\n\n"
        + grounding_block("The room topic, context, and transcript in this message")
        + "\n\n"
        "Transcript messages are prefixed with their author's name. Read the whole "
        "thread, then address the most recent open question or the point most "
        "relevant to the topic. It is fine to disagree with any participant.\n"
        "This is a chat message, not a report: a few sentences to a few short "
        f"paragraphs at most, and never more than {_MAX_REPLY_CHARS} characters — "
        "longer replies are rejected outright.\n"
        "Never write as or quote-fabricate another participant. Output exactly the "
        f"message body — no '{name}:' prefix, no surrounding code fences, no meta "
        "commentary.\n"
        "If the room has no messages yet, open the discussion of the topic and "
        "context."
    )


def _room_prompt(room: dict[str, Any], transcript: list[dict[str, Any]]) -> str:
    parts = [f"Topic: {room['topic']}"]
    if room.get("context"):
        parts.append(f"Context: {room['context']}")
    if transcript:
        lines = "\n\n".join(f"{m['author']}: {m['body']}" for m in transcript)
        parts.append(f"Transcript:\n\n{lines}")
    else:
        parts.append("The room has no messages yet.")
    return "\n\n".join(parts)


def _raise_contract_error(message: str) -> None:
    from services.graphs.runtime import GraphContractError

    raise GraphContractError(message)


async def _read(state: State) -> dict[str, Any]:
    participant = find_participant(state["participant"])
    room = None
    messages = []
    cursor = 0
    attempt = asyncio.timeout(_TRANSCRIPT_READ_SECONDS)
    try:
        async with attempt:
            while True:
                page = await asyncio.to_thread(get_room, state["room_id"], cursor)
                current_room = page["room"]
                if current_room.get("id") != state["room_id"]:
                    _raise_contract_error("Chat transcript page belongs to a different room.")
                if current_room.get("state") != "open":
                    _raise_contract_error(f"Chat room {state['room_id']} is closed; not generating a reply.")
                if room is None:
                    room = dict(current_room)
                if not isinstance(page.get("messages"), list) or type(page.get("has_more")) is not bool:
                    _raise_contract_error("Chat transcript page requires messages and a boolean has_more.")
                previous = cursor
                for message in page["messages"]:
                    if not isinstance(message, dict):
                        _raise_contract_error("Chat transcript messages must be objects with increasing IDs.")
                    key = message.get("id")
                    if type(key) is not int or key <= cursor:
                        _raise_contract_error("Chat transcript message IDs must advance in strictly increasing order.")
                    cursor = key
                    messages.append(dict(message))
                if type(page.get("last_message_id")) is not int or page["last_message_id"] != cursor:
                    _raise_contract_error("Chat transcript cursor does not match its final message.")
                if page["has_more"] and cursor == previous:
                    _raise_contract_error("Chat transcript pagination made no progress.")
                if not page["has_more"]:
                    break
    except TimeoutError:
        if not attempt.expired():
            raise
        _raise_contract_error(f"Chat transcript read exceeded its {_TRANSCRIPT_READ_SECONDS:g}-second deadline; no reply was generated.")

    # Room metadata and the immutable message prefix are frozen before model invocation.
    return {
        "participant": participant.name,
        "model_role": participant.model_role,
        "room": room,
        "transcript": messages,
    }


async def _reply(state: State) -> dict[str, Any]:
    others = [p.name for p in chat_participants() if p.name != state["participant"]]
    model = build_chat_model(state["model_role"], fallback_role=CHAT_MODEL_ROLE)
    response = await model.ainvoke(
        [
            SystemMessage(content=_system_prompt(state["participant"], others)),
            HumanMessage(
                content=_room_prompt(state["room"], state["transcript"])
            ),
        ]
    )
    text = extract_text(response).strip()
    if not text:
        _raise_contract_error(
            f"Chat graph model returned an empty reply for participant "
            f"{state['participant']!r}."
        )
    if len(text) > _MAX_REPLY_CHARS:
        _raise_contract_error(
            f"Chat graph model returned {len(text)} characters for participant "
            f"{state['participant']!r}; replies must be {_MAX_REPLY_CHARS} "
            "characters or fewer. Nothing was posted."
        )
    return {"draft": text}


def _post(state: State) -> dict[str, Any]:
    message = post_graph_message(state["room_id"], state["participant"], state["draft"])
    return {
        "result": {
            "message": message,
            "room": {
                "id": state["room"]["id"],
                "topic": state["room"]["topic"],
                "state": state["room"]["state"],
            },
            "author": state["participant"],
            "transcript_truncated": False,
        }
    }


def build_graph():
    graph = StateGraph(State)
    graph.add_node("read", _read)
    graph.add_node("reply", _reply)
    graph.add_node("post", _post)
    graph.add_edge(START, "read")
    graph.add_edge("read", "reply")
    graph.add_edge("reply", "post")
    graph.add_edge("post", END)
    return graph.compile()
