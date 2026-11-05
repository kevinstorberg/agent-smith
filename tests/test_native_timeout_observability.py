from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import HumanMessage

from services.graphs import model_factory
from services.graphs.model_config import load_model_config
from services.meetings.types import MeetingProviderError
from services.observability import billable_operation, current_trigger
from tests.test_eval_call_observability import scripted_runner as scripted_runner
from tests.test_graph_model_factory import model_env as model_env
from tests.test_granola_observability import provider_for

SECRET = "PRIVATE_NATIVE_TIMEOUT_CONTENT"


def events(caplog):
    return [
        record.billable_event
        for record in caplog.records
        if hasattr(record, "billable_event")
    ]


def native_timeout(module_name, class_name):
    module = pytest.importorskip(module_name)
    kind = getattr(module, class_name)
    if module_name in {"openai", "anthropic"}:
        return kind(
            request=httpx.Request("GET", f"https://never-contact.invalid/{SECRET}")
        )
    if module_name == "urllib3.exceptions" and class_name == "ReadTimeoutError":
        return kind(None, f"https://never-contact.invalid/{SECRET}", SECRET)
    if module_name == "botocore.exceptions":
        return kind(
            endpoint_url=f"https://never-contact.invalid/{SECRET}", error=SECRET
        )
    return kind(SECRET)


@pytest.mark.parametrize(
    "module_name,class_name",
    [
        ("httpx", "ReadTimeout"),
        ("httpx", "ConnectTimeout"),
        ("openai", "APITimeoutError"),
        ("anthropic", "APITimeoutError"),
        ("urllib3.exceptions", "ReadTimeoutError"),
        ("urllib3.exceptions", "ConnectTimeoutError"),
        ("google.api_core.exceptions", "DeadlineExceeded"),
        ("botocore.exceptions", "ConnectTimeoutError"),
        ("botocore.exceptions", "ReadTimeoutError"),
    ],
)
def test_native_timeout_mro_classification_preserves_error_and_private_details(
    caplog, module_name, class_name
):
    error = native_timeout(module_name, class_name)
    with pytest.raises(type(error)) as raised:
        with billable_operation("synthetic", "request"):
            raise error
    assert raised.value is error
    before, after = events(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == "timeout"
    assert after["error_type"] == class_name and SECRET not in caplog.text
    assert all(
        record.exc_info is None
        for record in caplog.records
        if hasattr(record, "billable_event")
    )
    assert current_trigger() == {}


@pytest.mark.parametrize(
    "name", ["APITimeoutError", "DeadlineExceeded", "ConnectionTimeoutFailure"]
)
def test_timeout_like_names_from_unlisted_modules_remain_failed(caplog, name):
    error = type(name, (RuntimeError,), {})(SECRET)
    with pytest.raises(type(error)):
        with billable_operation("synthetic", "request"):
            raise error
    assert events(caplog)[-1]["outcome"] == "failed" and SECRET not in caplog.text


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_runner_native_sdk_timeout_keeps_identity_and_timeout_outcome(
    scripted_runner, caplog, provider
):
    from evals.shared import runner

    error = native_timeout(provider, "APITimeoutError")
    model, _ = scripted_runner(provider, error, "create")
    with pytest.raises(type(error)) as raised:
        runner.run_agent(model, SECRET)
    assert raised.value is error
    assert len(events(caplog)) == 2 and events(caplog)[-1]["outcome"] == "timeout"
    assert SECRET not in caplog.text


def test_model_callback_native_timeout_keeps_safe_terminal_type(
    model_env, monkeypatch, caplog
):
    monkeypatch.setattr(model_factory, "require_model_calls_allowed", lambda: None)
    guard = model_factory._ModelGuard(load_model_config("opinion"))
    run_id = uuid4()
    guard.on_chat_model_start({}, [[HumanMessage(content=SECRET)]], run_id=run_id)
    error = native_timeout("openai", "APITimeoutError")
    guard.on_llm_error(error, run_id=run_id)
    assert (
        events(caplog)[-1]["outcome"] == "timeout"
        and events(caplog)[-1]["error_type"] == "APITimeoutError"
    )
    assert guard._events == {} and SECRET not in caplog.text


@pytest.mark.asyncio
async def test_granola_native_timeout_keeps_four_attempts_and_public_error(caplog):
    def handler(request):
        raise httpx.ReadTimeout(SECRET, request=request)

    provider, _ = provider_for(handler)
    try:
        with pytest.raises(MeetingProviderError) as raised:
            await provider.list_page()
    finally:
        await provider.aclose()
    assert str(raised.value) == "Granola connection failed after four attempts"
    assert len(events(caplog)) == 8
    assert [event["attempt"] for event in events(caplog)[::2]] == [1, 2, 3, 4]
    assert all(
        event["outcome"] == "timeout" and event["error_type"] == "ReadTimeout"
        for event in events(caplog)[1::2]
    )
    assert SECRET not in caplog.text and current_trigger() == {}
