from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from inspect import iscoroutinefunction
from pathlib import Path

from deepeval import models
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams
from scripts.shared.automated_tests import require_model_calls_allowed
from services.observability import billable_operation
from services.rubric import rule_to_eval_steps

JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "gpt-5.4")

_PROVIDERS = {
    "OpenAIModel": "openai", "AzureOpenAIModel": "azure_openai", "AnthropicModel": "anthropic",
    "GeminiModel": "gemini", "AmazonBedrockModel": "bedrock", "OllamaModel": "ollama",
    "LocalModel": "local", "LiteLLMModel": "litellm", "PortkeyModel": "portkey",
    "KimiModel": "kimi", "GrokModel": "grok", "DeepSeekModel": "deepseek", "OpenRouterModel": "openrouter",
}


def _observe_model(model) -> None:
    if model is None:
        return
    provider = next((provider for name, provider in _PROVIDERS.items() if isinstance(model, getattr(models, name))), "deepeval")
    active: ContextVar[bool] = ContextVar("judge_generation_active", default=False)

    @contextmanager
    def operation(name):
        require_model_calls_allowed()
        if active.get():
            yield
            return
        token = active.set(True)
        try:
            with billable_operation(provider, name, stage="evaluation_judge", model_role="eval_judge", model=model.get_model_name()):
                yield
        finally:
            active.reset(token)

    def observed(method, name):
        if iscoroutinefunction(method):
            @wraps(method)
            async def asynchronous(*args, **kwargs):
                with operation(name):
                    return await method(*args, **kwargs)
            return asynchronous

        @wraps(method)
        def synchronous(*args, **kwargs):
            with operation(name):
                return method(*args, **kwargs)
        return synchronous

    # Keep the selected native object so DeepEval's capability and cost contracts remain authoritative.
    for name in ("generate", "a_generate", "generate_raw_response", "a_generate_raw_response"):
        method = getattr(model, name, None)
        if callable(method):
            setattr(model, name, observed(method, name))


def _rule_to_steps(rule_content: str) -> list[str]:
    return rule_to_eval_steps(rule_content)


def evaluate(
    input: str,
    output: str,
    rule_path: str = "",
    threshold: float = 0.0,
    rule_name: str | None = None,
    rule_content: str | None = None,
    judge_prompt: str = "",
) -> dict:
    require_model_calls_allowed()
    assert judge_prompt, "judge_prompt is required."
    if rule_content is None:
        assert rule_path, "Either rule_path or rule_content must be provided."
        rule_content = Path(rule_path).read_text(encoding="utf-8")
    if rule_name is None:
        rule_name = Path(rule_path).stem if rule_path else "unnamed"

    steps = _rule_to_steps(rule_content)
    criteria = f"{judge_prompt}\n\nRule:\n{rule_content}"

    metric = GEval(
        name=rule_name,
        model=JUDGE_MODEL,
        criteria=criteria,
        evaluation_steps=steps if steps else None,
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=threshold,
    )
    _observe_model(metric.model)
    test_case = LLMTestCase(input=input, actual_output=output)
    metric.measure(test_case, _additional_context=criteria)
    return {
        "rule": rule_name,
        "score": metric.score,
        "reason": metric.reason,
    }
