import asyncio

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from services.api.operation_context import request_trigger
from services.jobs import scheduler
from services.observability import billable_operation, current_trigger, trigger_context


pytestmark = pytest.mark.usefixtures("terminal_diagnostics")


def events(caplog):
    return [
        record.billable_event
        for record in caplog.records
        if hasattr(record, "billable_event")
    ]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_http_provider_context_uses_route_template_without_request_payload(
    caplog, asynchronous
):
    app = FastAPI(dependencies=[Depends(request_trigger)])

    def invoke_provider():
        with billable_operation("synthetic", "request"):
            return current_trigger()

    if asynchronous:

        @app.get("/api/probe/{item_id}")
        async def endpoint(item_id: str):
            await asyncio.sleep(0)
            return invoke_provider()
    else:

        @app.get("/api/probe/{item_id}")
        def endpoint(item_id: str):
            return invoke_provider()

    with TestClient(app) as client:
        first = client.get("/api/probe/private-payload?token=private-query").json()
        second = client.get("/api/probe/another-payload").json()

    assert first["trigger"] == "http.GET"
    assert first["source"] == "/api/probe/{item_id}"
    assert first["request_id"] != second["request_id"]
    assert current_trigger() == {}
    recorded = events(caplog)
    assert [event["phase"] for event in recorded] == ["START", "END", "START", "END"]
    assert all(event["source"] == "/api/probe/{item_id}" for event in recorded)
    assert all(
        "private-payload" not in str(event) and "private-query" not in str(event)
        for event in recorded
    )


def test_failed_http_request_closes_operation_and_does_not_leak_context(caplog):
    app = FastAPI(dependencies=[Depends(request_trigger)])

    @app.get("/api/failure")
    async def endpoint():
        with billable_operation("synthetic", "request"):
            raise ValueError("private-response-body")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/api/failure").status_code == 500

    start, end = events(caplog)
    assert start["event_id"] == end["event_id"]
    assert end["outcome"] == "failed"
    assert end["error_type"] == "ValueError"
    assert "private-response-body" not in str(end)
    assert current_trigger() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic", [False, True])
async def test_job_provider_retains_parent_request_and_execution_context(
    monkeypatch, caplog, automatic
):
    monkeypatch.setattr(scheduler, "create_execution", lambda **kwargs: 42)
    captured = []

    async def run(exec_id, job_id, graph_type, params):
        with billable_operation("synthetic", "job"):
            captured.append(current_trigger())
        return {"success": True}

    monkeypatch.setattr(scheduler, "_run_graph_job", run)
    with trigger_context(
        trigger="http.POST", source="/api/jobs/{id}/run", request_id="request-fixture"
    ):
        result = await scheduler.execute_job(
            {"id": 7, "input_params": {"graph_type": "echo"}}, automatic=automatic
        )
        assert current_trigger()["trigger"] == "http.POST"

    assert result == {"success": True, "execution_id": 42}
    assert captured[0]["trigger"] == ("job.scheduled" if automatic else "job.manual")
    assert captured[0]["origin"] == "http.POST"
    assert captured[0]["request_id"] == "request-fixture"
    assert captured[0]["job_id"] == 7 and captured[0]["execution_id"] == 42
    assert current_trigger() == {}
    assert events(caplog)[-1]["outcome"] == "success"


@pytest.mark.asyncio
async def test_cancelled_job_preserves_exception_and_cleans_trigger(
    monkeypatch, caplog
):
    monkeypatch.setattr(scheduler, "create_execution", lambda **kwargs: 42)
    cancelled = asyncio.CancelledError()

    async def run(*args):
        with billable_operation("synthetic", "job"):
            raise cancelled

    monkeypatch.setattr(scheduler, "_run_graph_job", run)
    with pytest.raises(asyncio.CancelledError) as caught:
        await scheduler.execute_job({"id": 7, "input_params": {"graph_type": "echo"}})

    assert caught.value is cancelled
    assert current_trigger() == {}
    assert events(caplog)[-1]["outcome"] == "cancelled"
