from __future__ import annotations

from collections.abc import Callable

from services.graphs.model_factory import build_chat_model

# Statuses the RubricMiddleware can end on that mean the run did not pass.
TERMINAL_FAILURES = {"max_iterations_reached", "failed", "grader_error"}


def rubric_status(evaluations: list[dict]) -> str:
    """The middleware reports rubric state only via the on_evaluation callback
    (its state keys are private and suppressed inside a parent graph). The last
    evaluation carries the terminal status, including middleware-synthesized
    ones like max_iterations_reached and grader_error."""
    if evaluations:
        result = evaluations[-1].get("result")
        if isinstance(result, str):
            return result
    return "missing_rubric_status"


def rubric_explanation(evaluations: list[dict]) -> str:
    for evaluation in reversed(evaluations):
        explanation = evaluation.get("explanation")
        if isinstance(explanation, str) and explanation:
            return explanation
    return "Rubric middleware produced no evaluations."


def create_rubric_agent(
    *,
    system_prompt: str,
    grader_prompt: str,
    max_iterations: int,
    model_role: str,
    on_evaluation: Callable[[dict], None] | None = None,
    tools: list | None = None,
):
    try:
        from deepagents import RubricMiddleware, create_deep_agent
    except ImportError as exc:
        raise RuntimeError(
            "deepagents>=0.6.5 is required for rubric-backed graph agents. "
            "Install requirements.txt before running this graph."
        ) from exc

    return create_deep_agent(
        model=build_chat_model(model_role),
        tools=tools or [],
        system_prompt=system_prompt,
        middleware=[
            RubricMiddleware(
                model=build_chat_model(f"{model_role}_grader", fallback_role=model_role),
                system_prompt=grader_prompt,
                max_iterations=max_iterations,
                on_evaluation=on_evaluation,
            ),
        ],
    )
