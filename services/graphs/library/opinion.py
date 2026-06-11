"""Opinion: returns a critical opinion on a proposed plan or architecture."""
from __future__ import annotations

import os
import re
from typing import Any, TypedDict
from uuid import uuid4

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

from scripts.shared.paths import REPO_ROOT
from services.rubric import rules_to_prompt_context, rules_to_rubric

MODEL = os.environ.get("OPINION_MODEL", "moonshotai/Kimi-K2.6")
PROVIDER = "openai-compatible"
MODEL_BASE_URL = os.environ.get("OPINION_MODEL_BASE_URL", "http://localhost:30000/v1")
MODEL_API_KEY = os.environ.get("OPINION_MODEL_API_KEY", "local-kimi")
RULE_AGENT = os.environ.get("OPINION_RULE_AGENT", "codex")
RULE_INCLUDE = os.environ.get(
    "OPINION_RULE_INCLUDE",
    "DRY,Easier To Change,Design by Contract,No Broken Windows,Tracer Bullets",
)
RUBRIC_MAX_ITERATIONS = os.environ.get("OPINION_RUBRIC_MAX_ITERATIONS", "3")
INPUT_SCHEMA = {"proposal": "string"}

_SYSTEM_PROMPT = (
    "You are a senior engineer giving a candid second opinion on a proposed plan or "
    "architecture. Be specific and honest. Cover, in this order:\n"
    "  1. What you think is sound about the proposal.\n"
    "  2. The single biggest risk or weakness you see.\n"
    "  3. One or two concrete simplifications or alternatives worth considering.\n"
    "  4. Any unstated assumptions the author should verify.\n"
    "Keep the response tight - prioritize signal over breadth. Do not flatter; do not "
    "hedge."
)

_GRADER_PROMPT = (
    "You are grading a senior engineering opinion against the supplied pragmatic "
    "engineering rubric. Mark satisfied only when the final opinion materially applies "
    "the rubric to the user's proposal. If the opinion is vague, flattering, avoids the "
    "biggest risk, duplicates logic, builds on a known bad foundation, omits boundary "
    "checks, or fails to recommend tracer-bullet verification when useful, return "
    "needs_revision with concrete feedback."
)

_TERMINAL_FAILURES = {"max_iterations_reached", "failed", "grader_error"}


class State(TypedDict):
    proposal: str
    result: str


def build_graph():
    rules = _load_selected_rules()
    prompt_context = rules_to_prompt_context(rules)
    rubric = rules_to_rubric(rules)
    agent = _create_opinion_agent(
        system_prompt=f"{_SYSTEM_PROMPT}\n\n{prompt_context}",
        max_iterations=_configured_max_iterations(),
    )

    async def _opine(state: State) -> State:
        proposal = state["proposal"]
        assert isinstance(proposal, str) and proposal.strip(), "proposal must be a non-empty string"

        result = await agent.ainvoke(
            {
                "messages": [HumanMessage(content=proposal)],
                "rubric": rubric,
            },
            config={"configurable": {"thread_id": f"opinion-{uuid4()}"}},
        )
        status = _rubric_status(result)
        if status != "satisfied":
            _raise_contract_error(status, _rubric_explanation(result))

        text = _extract_result_text(result)
        if not text.strip():
            _raise_contract_error("empty_result", "Opinion graph returned an empty response.")
        return {"proposal": proposal, "result": text}

    g = StateGraph(State)
    g.add_node("opine", _opine)
    g.add_edge(START, "opine")
    g.add_edge("opine", END)
    return g.compile()


def _build_kimi_model() -> ChatOpenAI:
    model = os.environ.get("OPINION_MODEL", MODEL)
    base_url = os.environ.get("OPINION_MODEL_BASE_URL", MODEL_BASE_URL)
    api_key = os.environ.get("OPINION_MODEL_API_KEY", MODEL_API_KEY)

    assert model.strip(), "OPINION_MODEL must be set"
    assert base_url.strip(), "OPINION_MODEL_BASE_URL must be set"
    assert api_key.strip(), "OPINION_MODEL_API_KEY must be set"

    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=1.0,
        top_p=0.95,
        extra_body={"chat_template_kwargs": {"thinking": True}},
    )


def _create_opinion_agent(system_prompt: str, max_iterations: int):
    try:
        from deepagents import RubricMiddleware, create_deep_agent
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError as exc:
        raise RuntimeError(
            "deepagents>=0.6.5 is required for the Opinion rubric loop. "
            "Install requirements.txt before running the opinion graph."
        ) from exc

    worker_model = _build_kimi_model()
    grader_model = _build_kimi_model()
    return create_deep_agent(
        model=worker_model,
        system_prompt=system_prompt,
        middleware=[
            RubricMiddleware(
                model=grader_model,
                system_prompt=_GRADER_PROMPT,
                max_iterations=max_iterations,
            ),
        ],
        checkpointer=InMemorySaver(),
    )


def _configured_max_iterations() -> int:
    raw = os.environ.get("OPINION_RUBRIC_MAX_ITERATIONS", RUBRIC_MAX_ITERATIONS)
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("OPINION_RUBRIC_MAX_ITERATIONS must be an integer") from exc
    if not 1 <= value <= 20:
        raise ValueError("OPINION_RUBRIC_MAX_ITERATIONS must be between 1 and 20")
    return value


def _load_selected_rules() -> list[tuple[str, str]]:
    from services.api.models.rule import collect_rules_from_db

    agent = os.environ.get("OPINION_RULE_AGENT", RULE_AGENT)
    include = _configured_rule_include()
    rules = collect_rules_from_db(agent, project=str(REPO_ROOT))
    return _filter_rules(rules, include)


def _configured_rule_include() -> list[str]:
    raw = os.environ.get("OPINION_RULE_INCLUDE", RULE_INCLUDE)
    return [name.strip() for name in raw.split(",") if name.strip()]


def _filter_rules(
    rules: list[tuple[str, str]],
    include: list[str] | None,
) -> list[tuple[str, str]]:
    if not include:
        if not rules:
            raise ValueError("Opinion graph found no enabled harness rules.")
        return rules

    include_keys = [_normalize_rule_label(name) for name in include]
    selected = [
        (name, body)
        for name, body in rules
        if _rule_matches_include(name, body, include_keys)
    ]
    if not selected:
        raise ValueError(
            "Opinion graph found no enabled harness rules matching "
            f"OPINION_RULE_INCLUDE={','.join(include)}"
        )
    return selected


def _rule_matches_include(name: str, body: str, include_keys: list[str]) -> bool:
    candidate = _normalize_rule_label(f"{name}\n{body[:500]}")
    return any(key and key in candidate for key in include_keys)


def _normalize_rule_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _rubric_status(result: Any) -> str:
    if isinstance(result, dict):
        status = result.get("_rubric_status")
        if isinstance(status, str):
            return status
        evaluations = result.get("_rubric_evaluations")
        if isinstance(evaluations, list) and evaluations:
            last = evaluations[-1]
            if isinstance(last, dict) and isinstance(last.get("result"), str):
                return last["result"]
    return "missing_rubric_status"


def _rubric_explanation(result: Any) -> str:
    if not isinstance(result, dict):
        return "DeepAgents returned a non-dict result."
    evaluations = result.get("_rubric_evaluations")
    if isinstance(evaluations, list) and evaluations:
        last = evaluations[-1]
        if isinstance(last, dict) and isinstance(last.get("explanation"), str):
            return last["explanation"]
    status = result.get("_rubric_status", "missing_rubric_status")
    return f"Rubric ended with status {status}."


def _extract_result_text(result: Any) -> str:
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            return _extract_text(messages[-1])
        output = result.get("output") or result.get("result")
        if output is not None:
            return _extract_text(output)
    return _extract_text(result)


def _extract_text(msg: Any) -> str:
    text = getattr(msg, "text", None)
    if isinstance(text, str):
        return text
    if callable(text):
        value = text()
        if isinstance(value, str):
            return value

    content = getattr(msg, "content", msg)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") if isinstance(p, dict) else str(p) for p in content]
        return "".join(parts)
    return str(content)


def _raise_contract_error(status: str, explanation: str) -> None:
    from services.graphs.runtime import GraphContractError

    if status in _TERMINAL_FAILURES:
        raise GraphContractError(
            f"Opinion rubric did not pass: {status}. {explanation}"
        )
    raise GraphContractError(f"Opinion graph contract failed: {status}. {explanation}")
