import asyncio

import pytest

from services.jobs import scheduler
from services.jobs.models.execution import get_execution
from services.jobs.models.job import create_job
from services.observability import current_trigger, trigger_context
from tests.conftest import jobs_cleanup

_clean = jobs_cleanup("BILLABLECMD %")


def records(caplog):
    return [
        record.billable_event
        for record in caplog.records
        if hasattr(record, "billable_event")
    ]


def assert_private_logs(caplog):
    for record in caplog.records:
        if hasattr(record, "billable_event"):
            assert "PRIVATE_" not in record.getMessage() and record.exc_info is None


class Stream:
    def __init__(self, data):
        self.data = data
        self.drained = False

    async def read(self, _):
        if self.data:
            data, self.data = self.data, b""
            return data
        self.drained = True
        return b""


class Process:
    def __init__(self, exit_code=0, error=None):
        self.stdout = Stream(b"PRIVATE_OUTPUT")
        self.stderr = Stream(b"PRIVATE_STDERR")
        self.returncode = exit_code
        self.error = error
        self.killed = False

    async def wait(self):
        if self.error is not None:
            raise self.error
        return self.returncode


@pytest.fixture
def ledger(monkeypatch, caplog):
    calls = []

    def complete(exec_id, **kwargs):
        assert [record["phase"] for record in records(caplog)] == ["START"]
        calls.append((exec_id, kwargs))

    monkeypatch.setattr(scheduler, "complete_execution", complete)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code,outcome", [(0, "success"), (7, "failed")])
async def test_command_pair_covers_spawn_pumps_and_ledger_without_logging_payload(
    monkeypatch, ledger, caplog, exit_code, outcome
):
    process = Process(exit_code)
    calls = []

    async def spawn(command, **kwargs):
        assert [record["phase"] for record in records(caplog)] == ["START"]
        assert current_trigger()["parent_event_id"] == records(caplog)[0]["event_id"]
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(scheduler.asyncio, "create_subprocess_shell", spawn)
    with trigger_context(
        trigger="http.POST", request_id="synthetic", reason="manual_request"
    ):
        result = await scheduler._run_command_job(
            42, 7, "PRIVATE_COMMAND", {"timeout": 3}
        )
        assert current_trigger() == {
            "trigger": "http.POST",
            "request_id": "synthetic",
            "reason": "manual_request",
        }
    assert result["success"] is (exit_code == 0) and result["exit_code"] == exit_code
    assert result["output"] == "PRIVATE_OUTPUT" and result["error"] == "PRIVATE_STDERR"
    assert process.stdout.drained and process.stderr.drained
    assert calls == [
        (
            "PRIVATE_COMMAND",
            {
                "stdout": asyncio.subprocess.PIPE,
                "stderr": asyncio.subprocess.PIPE,
                "start_new_session": True,
            },
        )
    ]
    assert ledger == [(42, {"status": outcome, "result": result})]
    before, after = records(caplog)
    assert (
        before["event_id"] == after["event_id"]
        and after["outcome"] == outcome
        and after["exit_code"] == exit_code
    )
    assert (before["provider"], before["operation"], before["stage"]) == (
        "command",
        "subprocess",
        "command_job",
    )
    assert (before["job_id"], before["execution_id"], before["request_id"]) == (
        7,
        42,
        "synthetic",
    )
    assert before["reason"] == "manual_request" and current_trigger() == {}
    assert_private_logs(caplog)


@pytest.mark.asyncio
async def test_timeout_pair_ends_after_group_kill_drain_and_original_timeout_ledger(
    monkeypatch, ledger, caplog
):
    process = Process(None, TimeoutError())

    async def spawn(*_, **__):
        return process

    def kill(proc):
        assert len(records(caplog)) == 1 and proc is process
        process.killed = True
        process.returncode = -9

    monkeypatch.setattr(scheduler.asyncio, "create_subprocess_shell", spawn)
    monkeypatch.setattr(scheduler, "_kill_process_group", kill)
    result = await scheduler._run_command_job(
        42, 7, "PRIVATE_COMMAND", {"timeout": 0.5}
    )
    assert process.killed and process.stdout.drained and process.stderr.drained
    assert result["success"] is False and result["exit_code"] is None
    assert result["output"] == "PRIVATE_OUTPUT"
    assert (
        result["error"]
        == "timed out after 0.5s\n--- partial stderr ---\nPRIVATE_STDERR"
    )
    assert ledger == [(42, {"status": "timeout", "result": result})]
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == "timeout"
    assert after["exit_code"] == -9 and current_trigger() == {}
    assert_private_logs(caplog)


@pytest.mark.asyncio
async def test_cancel_pair_preserves_original_exception_after_kill_and_synchronous_ledger(
    monkeypatch, ledger, caplog
):
    failure = asyncio.CancelledError("PRIVATE_CANCEL")
    process = Process(None, failure)

    async def spawn(*_, **__):
        return process

    def kill(proc):
        assert len(records(caplog)) == 1 and proc is process
        process.killed = True

    monkeypatch.setattr(scheduler.asyncio, "create_subprocess_shell", spawn)
    monkeypatch.setattr(scheduler, "_kill_process_group", kill)
    with pytest.raises(asyncio.CancelledError) as raised:
        await scheduler._run_command_job(42, 7, "PRIVATE_COMMAND", {})
    assert raised.value is failure and process.killed
    assert ledger[0][1]["status"] == "interrupted"
    assert ledger[0][1]["result"]["error"] == "cancelled (scheduler shutdown)"
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["outcome"] == "cancelled"
    assert after["error_type"] == "CancelledError" and current_trigger() == {}
    assert_private_logs(caplog)


@pytest.mark.asyncio
async def test_actual_task_cancellation_still_finalizes_before_end(
    monkeypatch, ledger, caplog
):
    entered = asyncio.Event()
    process = Process(None)

    async def wait():
        entered.set()
        await asyncio.Event().wait()

    async def spawn(*_, **__):
        return process

    process.wait = wait
    monkeypatch.setattr(scheduler.asyncio, "create_subprocess_shell", spawn)
    monkeypatch.setattr(
        scheduler, "_kill_process_group", lambda _: setattr(process, "killed", True)
    )
    task = asyncio.create_task(scheduler._run_command_job(42, 7, "PRIVATE_COMMAND", {}))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert process.killed and ledger[0][1]["status"] == "interrupted"
    assert len(records(caplog)) == 2 and records(caplog)[-1]["outcome"] == "cancelled"


@pytest.mark.asyncio
async def test_spawn_failure_keeps_error_contract_and_redacts_new_events(
    monkeypatch, ledger, caplog
):
    failure = OSError("PRIVATE_OS_FAILURE")

    async def spawn(*_, **__):
        assert len(records(caplog)) == 1
        raise failure

    monkeypatch.setattr(scheduler.asyncio, "create_subprocess_shell", spawn)
    result = await scheduler._run_command_job(42, 7, "PRIVATE_COMMAND", {})
    assert (
        result["success"] is False and result["error"] == "OSError: PRIVATE_OS_FAILURE"
    )
    assert ledger == [(42, {"status": "failed", "result": result})]
    before, after = records(caplog)
    assert (
        before["event_id"] == after["event_id"]
        and after["outcome"] == "failed"
        and after["error_type"] == "OSError"
    )
    assert current_trigger() == {}
    assert_private_logs(caplog)


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize(
    "params,admitted",
    [
        ({}, True),
        ({"command": "PRIVATE_COMMAND", "graph_type": "echo"}, True),
        ({"command": "PRIVATE_COMMAND", "timeout": "bad"}, True),
        ({"command": "PRIVATE_COMMAND"}, False),
    ],
)
async def test_nonexecuted_or_invalid_job_does_not_claim_a_paid_operation(
    monkeypatch, caplog, params, admitted, automatic
):
    writes = []
    monkeypatch.setattr(
        scheduler, "create_execution", lambda **_: 42 if admitted else None
    )
    monkeypatch.setattr(
        scheduler,
        "complete_execution",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )

    async def spawn(*_, **__):
        pytest.fail("Invalid job must not spawn")

    monkeypatch.setattr(scheduler.asyncio, "create_subprocess_shell", spawn)
    result = await scheduler.execute_job(
        {"id": 7, "input_params": params}, automatic=automatic
    )
    assert result["success"] is (automatic and not admitted)
    if not admitted:
        assert result["skipped"] is True and "execution_id" not in result
        if not automatic:
            assert "not active" in result["error"].lower()
    assert (
        bool(writes) is admitted and records(caplog) == [] and current_trigger() == {}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_code", [0, 3])
async def test_real_subprocess_and_native_execution_ledger_keep_results_and_correlation(
    caplog, exit_code
):
    command = f"echo PRIVATE_COMMAND_OUTPUT; exit {exit_code}"
    job_id = create_job(
        name="BILLABLECMD Native",
        schedule_config={"minutes": 5},
        input_params={"command": command},
    )
    with trigger_context(trigger="mcp", request_id="synthetic"):
        result = await scheduler.execute_job(
            {"id": job_id, "input_params": {"command": command}}
        )
    execution = get_execution(result["execution_id"])
    assert result["success"] is (exit_code == 0) and result["exit_code"] == exit_code
    assert result["output"] == "PRIVATE_COMMAND_OUTPUT\n"
    assert execution["status"] == ("success" if exit_code == 0 else "failed")
    assert execution["result"] == {
        key: value for key, value in result.items() if key != "execution_id"
    }
    before, after = records(caplog)
    assert before["event_id"] == after["event_id"] and after["exit_code"] == exit_code
    assert (
        before["job_id"] == job_id and before["execution_id"] == result["execution_id"]
    )
    assert (
        before["trigger"] == "job.manual"
        and before["origin"] == "mcp"
        and before["request_id"] == "synthetic"
    )
    assert current_trigger() == {}
    assert_private_logs(caplog)
