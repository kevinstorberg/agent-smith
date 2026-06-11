from __future__ import annotations

from services.graphs.model_factory import build_chat_model


def create_rubric_agent(
    *,
    system_prompt: str,
    grader_prompt: str,
    max_iterations: int,
    model_role: str,
):
    try:
        from deepagents import RubricMiddleware, create_deep_agent
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError as exc:
        raise RuntimeError(
            "deepagents>=0.6.5 is required for rubric-backed graph agents. "
            "Install requirements.txt before running this graph."
        ) from exc

    return create_deep_agent(
        model=build_chat_model(model_role),
        system_prompt=system_prompt,
        middleware=[
            RubricMiddleware(
                model=build_chat_model(f"{model_role}_grader", fallback_role=model_role),
                system_prompt=grader_prompt,
                max_iterations=max_iterations,
            ),
        ],
        checkpointer=InMemorySaver(),
    )
