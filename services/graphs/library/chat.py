"""Chat: posts one AI reply into a Chat Room as a named chat participant."""
from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from scripts.shared.agents import AGENT_TARGETS
from services.chat.participants import chat_participants, find_participant
from services.chat.service import get_room, post_graph_message
from services.graphs.messages import extract_text
from services.graphs.model_factory import build_chat_model
from services.graphs.prompts import grounding_block

INPUT_SCHEMA = {"room_id": "integer", "participant": "string"}

_MAX_TRANSCRIPT_PAGES = 50
_MAX_TRANSCRIPT_MESSAGES = 200
_MAX_REPLY_CHARS = 6_000

# Harness rules are deliberately NOT injected here: the rules assigned to the
# "opinion" virtual agent are plan-critique principles, the wrong register for
# a conversational reply. Chat-specific steering would be a new virtual agent.


class State(TypedDict):
    room_id: int
    participant: str
    model_id: str
    room: dict[str, Any]
    transcript: list[dict[str, Any]]
    transcript_truncated: bool
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


def _room_prompt(room: dict[str, Any], transcript: list[dict[str, Any]], truncated: bool) -> str:
    parts = [f"Topic: {room['topic']}"]
    if room.get("context"):
        parts.append(f"Context: {room['context']}")
    if truncated:
        parts.append("Note: earlier messages were omitted; only the most recent are shown.")
    if transcript:
        lines = "\n\n".join(f"{m['author']}: {m['body']}" for m in transcript)
        parts.append(f"Transcript:\n\n{lines}")
    else:
        parts.append("The room has no messages yet.")
    return "\n\n".join(parts)


def _raise_contract_error(message: str) -> None:
    from services.graphs.runtime import GraphContractError

    raise GraphContractError(message)


def _read(state: State) -> dict[str, Any]:
    participant = find_participant(state["participant"])

    page = get_room(state["room_id"])
    room = page["room"]
    if room["state"] == "closed":
        _raise_contract_error(
            f"Chat room {state['room_id']} is closed; not generating a reply."
        )

    messages = list(page["messages"])
    pages_read = 1
    while page["has_more"] and pages_read < _MAX_TRANSCRIPT_PAGES:
        page = get_room(state["room_id"], page["last_message_id"])
        messages.extend(page["messages"])
        pages_read += 1

    truncated = page["has_more"] or len(messages) > _MAX_TRANSCRIPT_MESSAGES
    return {
        "participant": participant.name,
        "model_id": participant.model_id,
        "room": room,
        "transcript": messages[-_MAX_TRANSCRIPT_MESSAGES:],
        "transcript_truncated": truncated,
    }


async def _reply(state: State) -> dict[str, Any]:
    others = [p.name for p in chat_participants() if p.name != state["participant"]]
    model = build_chat_model("chat", model_id=state["model_id"])
    response = await model.ainvoke(
        [
            SystemMessage(content=_system_prompt(state["participant"], others)),
            HumanMessage(
                content=_room_prompt(
                    state["room"], state["transcript"], state["transcript_truncated"]
                )
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
            "transcript_truncated": state["transcript_truncated"],
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
