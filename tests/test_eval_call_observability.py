import asyncio
from dataclasses import replace
from inspect import iscoroutinefunction
from types import SimpleNamespace

from deepeval import models
from deepeval.metrics import GEval
from deepeval.metrics.utils import models as selection
import pytest

from evals.shared import judge, runner
from scripts.shared.automated_tests import PaidModelCallBlocked
from services.observability import current_trigger, trigger_context


def records(caplog):
    return [
        record.billable_event
        for record in caplog.records
        if hasattr(record, "billable_event")
    ]


@pytest.fixture
def scripted_runner(monkeypatch, caplog):
    import anthropic
    import google.generativeai as genai
    import openai

    monkeypatch.setattr(runner, "require_model_calls_allowed", lambda: None)
    monkeypatch.setattr(runner, "_load_rules_context", lambda: "PRIVATE_SYSTEM")
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setenv(key, "fake-key")

    def install(provider, failure=None, fail_at="iteration"):
        calls = []

        def started(phase):
            assert [record["phase"] for record in records(caplog)] == ["START"]
            calls.append(phase)
            if failure is not None and fail_at == phase:
                raise failure

        def texts():
            started("iteration")
            yield "PRIVATE_REPLY"
            yield None
            yield " tail"

        class Stream:
            def __enter__(self):
                started("enter")
                return self

            def __exit__(self, *_):
                started("close")

            @property
            def text_stream(self):
                return texts()

            def __iter__(self):
                return (
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))]
                    )
                    for text in texts()
                )

        def create(**kwargs):
            started("create")
            calls.append(kwargs)
            return Stream()

        if provider == "anthropic":
            monkeypatch.setattr(
                anthropic,
                "Anthropic",
                lambda **_: SimpleNamespace(messages=SimpleNamespace(stream=create)),
            )
            model = "claude-test"
        elif provider == "openai":
            monkeypatch.setattr(
                openai,
                "OpenAI",
                lambda **_: SimpleNamespace(
                    chat=SimpleNamespace(completions=SimpleNamespace(create=create))
                ),
            )
            model = "gpt-test"
        else:

            def generate(prompt, **kwargs):
                started("create")
                calls.append({"prompt": prompt, **kwargs})
                return (SimpleNamespace(text=text) for text in texts())

            monkeypatch.setattr(genai, "configure", lambda **_: None)
            monkeypatch.setattr(
                genai,
                "GenerativeModel",
                lambda *_, **__: SimpleNamespace(generate_content=generate),
            )
            model = "gemini-test"
        return model, calls

    return install


@pytest.mark.parametrize("provider", ["anthropic", "openai", "gemini"])
def test_runner_covers_sdk_entry_collection_and_supported_cleanup(
    scripted_runner, provider, caplog, capsys
):
    model, calls = scripted_runner(provider)
    with trigger_context(trigger="mcp", tool="evals", request_id="synthetic"):
        assert (
            runner.run_agent(model, "PRIVATE_INPUT", "PRIVATE_EXTRA")
            == "PRIVATE_REPLY tail"
        )

    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == "success"
    assert (before["provider"], before["stage"], before["model_role"]) == (
        provider,
        "evaluation_agent",
        "eval_agent",
    )
    assert before["model"] == model and before["streaming"] is True
    assert before["trigger"] == "mcp" and before["request_id"] == "synthetic"
    assert calls[-1] == ("iteration" if provider == "gemini" else "close")
    assert current_trigger() == {}
    assert capsys.readouterr().out == "PRIVATE_REPLY tail\n"
    assert "PRIVATE_" not in caplog.text and "fake-key" not in caplog.text
    kwargs = next(call for call in calls if isinstance(call, dict))
    if provider != "gemini":
        assert kwargs["max_tokens"] == 16384
    if provider == "openai":
        assert kwargs["messages"] == [
            {"role": "system", "content": "PRIVATE_SYSTEM\n\nPRIVATE_EXTRA"},
            {"role": "user", "content": "PRIVATE_INPUT"},
        ]
    elif provider == "anthropic":
        assert kwargs["system"] == "PRIVATE_SYSTEM\n\nPRIVATE_EXTRA"


@pytest.mark.parametrize(
    "provider,phase",
    [
        (provider, phase)
        for provider in ("anthropic", "openai", "gemini")
        for phase in ("create", "iteration")
    ]
    + [("openai", "close"), ("anthropic", "close")],
)
@pytest.mark.parametrize(
    "kind,outcome",
    [
        (RuntimeError, "failed"),
        (TimeoutError, "timeout"),
        (asyncio.CancelledError, "cancelled"),
        (KeyboardInterrupt, "cancelled"),
    ],
)
def test_runner_failures_keep_original_exception_and_pair(
    scripted_runner, provider, phase, kind, outcome, caplog
):
    failure = kind("PRIVATE_ERROR")
    model, calls = scripted_runner(provider, failure, phase)
    with pytest.raises(kind) as raised:
        runner.run_agent(model, "PRIVATE_INPUT")

    assert raised.value is failure
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"]
    assert after["outcome"] == outcome and after["error_type"] == kind.__name__
    if phase == "iteration" and provider != "gemini":
        assert calls[-1] == "close"
    assert "PRIVATE_" not in caplog.text and current_trigger() == {}


@pytest.mark.parametrize("entry", ["runner", "judge"])
def test_automated_guard_produces_no_billable_event(monkeypatch, caplog, entry):
    monkeypatch.setattr(
        runner, "_load_rules_context", lambda: pytest.fail("guard must precede context")
    )
    monkeypatch.setattr(
        judge, "GEval", lambda **_: pytest.fail("guard must precede metric")
    )
    with pytest.raises(PaidModelCallBlocked):
        if entry == "runner":
            runner.run_agent("gpt-test", "PRIVATE_INPUT")
        else:
            judge.evaluate(
                "PRIVATE_INPUT",
                "PRIVATE_OUTPUT",
                rule_content="PRIVATE_RULE",
                judge_prompt="PRIVATE_CRITERIA",
            )
    assert records(caplog) == []


@pytest.fixture
def native_judge(monkeypatch, caplog):
    monkeypatch.setattr(judge, "require_model_calls_allowed", lambda: None)
    monkeypatch.setattr(judge, "JUDGE_MODEL", "gpt-4o")
    for name in dir(selection):
        if name.startswith("should_use_"):
            monkeypatch.setattr(selection, name, lambda: False)
    calls = []

    def response(kind, kwargs):
        assert records(caplog)[-1]["phase"] == "START"
        calls.append((kind, kwargs))
        schema = kwargs.get("response_format")
        parsed = None
        if isinstance(schema, type):
            values = (
                {"steps": ["PRIVATE_STEP"]}
                if "steps" in schema.model_fields
                else {"score": 8, "reason": "PRIVATE_REASON"}
            )
            parsed = schema(**values)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        parsed=parsed,
                        content='{"score": 8, "reason": "PRIVATE_REASON"}',
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4),
        )

    def client(asynchronous):
        def sync(kind):
            return lambda **kwargs: response(kind, kwargs)

        def async_call(kind):
            async def call(**kwargs):
                return response(kind, kwargs)

            return call

        call = async_call if asynchronous else sync
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=call("raw"))),
            beta=SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(parse=call("schema")))
            ),
        )

    monkeypatch.setattr(
        models.OpenAIModel, "load_model", lambda _, async_mode=False: client(async_mode)
    )
    return calls


@pytest.mark.parametrize("supplied_steps", [False, True])
@pytest.mark.parametrize("log_probs", [False, True])
def test_actual_geval_logs_step_generation_and_native_raw_or_schema_score(
    native_judge, monkeypatch, caplog, supplied_steps, log_probs
):
    metrics = []

    def metric(**kwargs):
        result = GEval(**kwargs)
        result.model.model_data = replace(
            result.model.model_data, supports_log_probs=log_probs
        )
        metrics.append(result)
        return result

    monkeypatch.setattr(judge, "GEval", metric)
    monkeypatch.setattr(
        judge, "_rule_to_steps", lambda _: ["PRIVATE_STEP"] if supplied_steps else []
    )
    with trigger_context(trigger="mcp", tool="evals", reason="manual_request"):
        result = judge.evaluate(
            "PRIVATE_INPUT",
            "PRIVATE_OUTPUT",
            rule_content="PRIVATE_RULE",
            rule_name="PRIVATE_NAME",
            judge_prompt="PRIVATE_CRITERIA",
        )

    assert result == {"rule": "PRIVATE_NAME", "score": 0.8, "reason": "PRIVATE_REASON"}
    metric = metrics[0]
    assert (
        type(metric.model) is models.OpenAIModel and metric.using_native_model is True
    )
    assert metric.evaluation_model == "gpt-4o" and metric.evaluation_cost > 0
    assert metric.model.supports_structured_outputs() is True
    assert [kind for kind, _ in native_judge] == (
        [] if supplied_steps else ["schema"]
    ) + ["raw" if log_probs else "schema"]
    result = records(caplog)
    assert len(result) == 2 * len(native_judge)
    for before, after in zip(result[::2], result[1::2]):
        assert before["event_id"] == after["event_id"] and after["outcome"] == "success"
        assert before["provider"] == "openai" and before["model_role"] == "eval_judge"
        assert before["trigger"] == "mcp" and before["reason"] == "manual_request"
    assert result[-2]["operation"] == (
        "a_generate_raw_response" if log_probs else "a_generate"
    )
    assert "PRIVATE_" not in caplog.text and current_trigger() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["generate", "a_generate", "generate_raw_response", "a_generate_raw_response"],
)
async def test_actual_native_generation_methods_reach_scripted_sdk(
    native_judge, caplog, name
):
    model = models.OpenAIModel("gpt-4o", api_key="fake")
    judge._observe_model(model)
    method = getattr(model, name)
    result, cost = (
        await method("PRIVATE_INPUT")
        if name.startswith("a_")
        else method("PRIVATE_INPUT")
    )
    assert cost > 0 and len(native_judge) == 1
    assert (
        result.choices[0].message.content if "raw_response" in name else result
    ) == '{"score": 8, "reason": "PRIVATE_REASON"}'
    before, after = records(caplog)
    assert before["operation"] == name and before["event_id"] == after["event_id"]
    assert after["outcome"] == "success" and "PRIVATE_" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["generate", "a_generate", "generate_raw_response", "a_generate_raw_response"],
)
async def test_native_public_wrappers_preserve_tuple_identity_and_capabilities(
    native_judge, caplog, name
):
    model = models.OpenAIModel("gpt-4o", api_key="fake")
    result = (object(), object())

    def synchronous(*_, **__):
        assert records(caplog)[-1]["phase"] == "START"
        return result

    async def asynchronous(*_, **__):
        return synchronous()

    setattr(model, name, asynchronous if name.startswith("a_") else synchronous)
    judge._observe_model(model)
    method = getattr(model, name)
    assert iscoroutinefunction(method) is name.startswith("a_")
    assert (
        await method("PRIVATE_INPUT")
        if name.startswith("a_")
        else method("PRIVATE_INPUT")
    ) is result
    assert selection.is_native_model(model) and model.supports_log_probs() is True
    assert len(records(caplog)) == 2 and "PRIVATE_INPUT" not in caplog.text


@pytest.mark.parametrize("name", ["generate", "a_generate"])
def test_bedrock_native_sync_async_delegation_has_one_pair(monkeypatch, caplog, name):
    monkeypatch.setattr(judge, "require_model_calls_allowed", lambda: None)
    model = object.__new__(models.AmazonBedrockModel)
    model.name = "synthetic-bedrock"
    result = (object(), object())

    async def call(*_, **__):
        assert len(records(caplog)) == 1
        return result

    model.a_generate = call
    judge._observe_model(model)
    actual = (
        model.generate("PRIVATE_INPUT")
        if name == "generate"
        else asyncio.run(model.a_generate("PRIVATE_INPUT"))
    )
    assert actual is result
    before, after = records(caplog)
    assert (
        before["provider"] == "bedrock"
        and before["operation"] == name
        and after["outcome"] == "success"
    )


@pytest.mark.asyncio
async def test_judge_task_local_nesting_isolates_cancellation_and_restores_context(
    native_judge, caplog
):
    model = models.OpenAIModel("gpt-4o", api_key="fake")
    entered = asyncio.Queue()
    release = asyncio.Event()

    async def call(*_, **__):
        entered.put_nowait(True)
        await release.wait()
        return "PRIVATE_OUTPUT", 1.0

    model.a_generate = call
    judge._observe_model(model)

    async def invoke(name):
        with trigger_context(request_id=name):
            return await model.a_generate("PRIVATE_INPUT")

    first = asyncio.create_task(invoke("first"))
    second = asyncio.create_task(invoke("second"))
    try:
        await asyncio.wait_for(entered.get(), 2)
        await asyncio.wait_for(entered.get(), 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert await second == ("PRIVATE_OUTPUT", 1.0)
    finally:
        release.set()
        for task in (first, second):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)
    assert len(records(caplog)) == 4
    for name, outcome in (("first", "cancelled"), ("second", "success")):
        before, after = [
            record for record in records(caplog) if record["request_id"] == name
        ]
        assert before["event_id"] == after["event_id"] and after["outcome"] == outcome
    await model.a_generate("PRIVATE_INPUT")
    assert len(records(caplog)) == 6 and current_trigger() == {}


def test_deepeval_provider_selection_flags_remain_authoritative(
    native_judge, monkeypatch, caplog
):
    metrics = []

    def initialize(self, **kwargs):
        assert kwargs == {"model": "gpt-4o"}
        self.name = "synthetic-deployment"
        self.model_data = models.OpenAIModel("gpt-4o", api_key="fake").model_data

        async def raw(*_args, **_kwargs):
            assert records(caplog)[-1]["provider"] == "azure_openai"
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"score": 8, "reason": "PRIVATE_REASON"}'
                        )
                    )
                ]
            ), 0.25

        self.a_generate_raw_response = raw

    def metric(**kwargs):
        result = GEval(**kwargs)
        metrics.append(result)
        return result

    monkeypatch.setattr(selection, "should_use_azure_openai", lambda: True)
    monkeypatch.setattr(models.AzureOpenAIModel, "__init__", initialize)
    monkeypatch.setattr(judge, "GEval", metric)
    monkeypatch.setattr(judge, "_rule_to_steps", lambda _: ["PRIVATE_STEP"])
    assert (
        judge.evaluate(
            "PRIVATE_INPUT",
            "PRIVATE_OUTPUT",
            rule_content="PRIVATE_RULE",
            judge_prompt="PRIVATE_CRITERIA",
        )["score"]
        == 0.8
    )
    assert (
        metrics[0].using_native_model
        and type(metrics[0].model) is models.AzureOpenAIModel
    )
    assert metrics[0].evaluation_cost == 0.25
    assert records(caplog)[0]["provider"] == "azure_openai"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,outcome",
    [
        (RuntimeError, "failed"),
        (TimeoutError, "timeout"),
        (asyncio.CancelledError, "cancelled"),
        (KeyboardInterrupt, "cancelled"),
    ],
)
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_judge_failure_preserves_exception_identity(
    native_judge, caplog, kind, outcome, asynchronous
):
    model = models.OpenAIModel("gpt-4o", api_key="fake")
    failure = kind("PRIVATE_ERROR")

    def sync(*_, **__):
        raise failure

    async def async_call(*_, **__):
        raise failure

    model.generate, model.a_generate = sync, async_call
    judge._observe_model(model)
    with pytest.raises(kind) as raised:
        if asynchronous:
            await model.a_generate("PRIVATE_INPUT")
        else:
            model.generate("PRIVATE_INPUT")
    assert raised.value is failure
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == outcome
    assert after["error_type"] == kind.__name__ and "PRIVATE_" not in caplog.text
