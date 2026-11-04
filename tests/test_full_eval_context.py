from dataclasses import replace
from types import SimpleNamespace

from deepeval import models
from deepeval.metrics import GEval
from deepeval.metrics.utils import models as selection
import pytest

from evals.shared import judge


def request_text(request):
    contents = [message["content"] for message in request["messages"]]
    return "\n".join(content if isinstance(content, str) else "\n".join(block["text"] for block in content)
                     for content in contents)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("raw_score", [False, True])
@pytest.mark.parametrize("numbered", [False, True])
def test_actual_geval_scoring_receives_complete_rule_and_judge_prompt(monkeypatch, asynchronous, raw_score, numbered):
    monkeypatch.setattr(judge, "require_model_calls_allowed", lambda: None)
    monkeypatch.setattr(judge, "JUDGE_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    for name in dir(selection):
        if name.startswith("should_use_"):
            monkeypatch.setattr(selection, name, lambda: False)
    requests, metrics = [], []
    rule = (
        "RULE_BEGIN\n  Keep original indentation.\n"
        + ("1. Apply the complete rule.\n2. Inspect every example.\n" if numbered else "Read all prose and examples.\n")
        + "```python\nprint('CODE_BEGIN')\n" + "    # rule source detail\n" * 500
        + "print('CODE_END')\n```\nRULE_END\n  "
    )
    judge_prompt = "JUDGE_BEGIN\n" + "Use every supplied instruction and example.\n" * 200 + "JUDGE_END"
    input_text = "INPUT_BEGIN\n" + "source input\n" * 500 + "INPUT_END"
    output_text = "OUTPUT_BEGIN\n" + "candidate response\n" * 500 + "OUTPUT_END"

    def response(kind, kwargs):
        requests.append((kind, kwargs))
        schema = kwargs.get("response_format")
        parsed = None
        if isinstance(schema, type):
            values = {"steps": ["A generated concise step"]} if "steps" in schema.model_fields else {"score": 8, "reason": "Complete context assessed"}
            parsed = schema(**values)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, content='{"score":8,"reason":"Complete context assessed"}'))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )

    def client(async_mode):
        def call(kind):
            if async_mode:
                async def asynchronous_call(**kwargs):
                    return response(kind, kwargs)
                return asynchronous_call
            return lambda **kwargs: response(kind, kwargs)
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=call("raw"))),
            beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=call("schema")))),
        )

    monkeypatch.setattr(models.OpenAIModel, "load_model", lambda _, async_mode=False: client(async_mode))

    def metric(**kwargs):
        instance = GEval(**kwargs, async_mode=asynchronous)
        instance.model.model_data = replace(instance.model.model_data, supports_log_probs=raw_score)
        metrics.append(instance)
        return instance

    monkeypatch.setattr(judge, "GEval", metric)
    result = judge.evaluate(input_text, output_text, rule_name="full-rule", rule_content=rule, judge_prompt=judge_prompt)

    assert result == {"rule": "full-rule", "score": 0.8, "reason": "Complete context assessed"}
    assert len(requests) == (1 if numbered else 2)
    assert requests[-1][0] == ("raw" if raw_score else "schema")
    scoring_prompt = request_text(requests[-1][1])
    assert judge_prompt in scoring_prompt
    assert rule in scoring_prompt
    assert input_text in scoring_prompt and output_text in scoring_prompt
    if not numbered:
        assert rule in request_text(requests[0][1])
        assert judge_prompt in request_text(requests[0][1])
    assert type(metrics[0].model) is models.OpenAIModel
    assert metrics[0].using_native_model and metrics[0].evaluation_cost > 0
