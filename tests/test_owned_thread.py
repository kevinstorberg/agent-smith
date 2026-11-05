from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from threading import Event, get_ident

import pytest


@pytest.fixture(params=["meeting", "shared"])
def runner(request):
    if request.param == "meeting":
        from services.meetings.service import run_db

        return run_db, "In-flight meeting DB operation failed"
    from scripts.shared.owned_thread import run_owned_thread

    async def run(operation):
        return await run_owned_thread(
            operation, failure_context="In-flight test operation failed"
        )

    return run, "In-flight test operation failed"


@pytest.mark.asyncio
async def test_owned_thread_preserves_return_identity_and_isolated_worker_context(
    runner,
):
    run, _ = runner
    context = ContextVar("owned-thread-test")
    parent_value, worker_value, result = object(), object(), object()
    marker = context.set(parent_value)
    parent_thread = get_ident()

    def operation():
        assert get_ident() != parent_thread
        assert context.get() is parent_value
        context.set(worker_value)
        return result

    try:
        assert await run(operation) is result
        assert context.get() is parent_value
    finally:
        context.reset(marker)


@pytest.mark.asyncio
async def test_owned_thread_preserves_normal_worker_error_identity_without_annotations(
    runner,
):
    run, _ = runner
    failure = LookupError("PRIVATE_WORKER_DETAIL")

    def operation():
        raise failure

    with pytest.raises(LookupError) as raised:
        await run(operation)
    assert raised.value is failure
    assert not getattr(failure, "__notes__", [])


@pytest.mark.asyncio
async def test_owned_thread_drains_repeated_cancellation_before_resource_exit(runner):
    run, _ = runner
    entered, release = Event(), Event()
    events = []

    def operation():
        entered.set()
        if not release.wait(5):
            raise RuntimeError("Test did not release owned worker")
        events.append("worker_done")

    @asynccontextmanager
    async def owner():
        events.append("owner_entered")
        try:
            yield
        finally:
            events.append("owner_exited")

    async def work():
        async with owner():
            await run(operation)

    task = asyncio.create_task(work())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel("first cancellation")
        await asyncio.sleep(0)
        for _ in range(3):
            task.cancel("later cancellation")
            await asyncio.sleep(0)
        assert not task.done()
        assert events == ["owner_entered"]
        release.set()
        with pytest.raises(asyncio.CancelledError) as raised:
            await asyncio.wait_for(task, 5)
        assert raised.value.args == ("first cancellation",)
        assert not getattr(raised.value, "__notes__", [])
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
    assert events == ["owner_entered", "worker_done", "owner_exited"]


@pytest.mark.asyncio
async def test_owned_thread_keeps_original_cancellation_identity_and_safe_worker_note(
    runner, monkeypatch
):
    run, prefix = runner
    entered, release = Event(), Event()
    cancelled = asyncio.CancelledError("original cancellation")
    cancelled.add_note("Existing caller note")
    real_shield = asyncio.shield
    injected = False

    def first_cancellation(task):
        nonlocal injected
        if not injected:
            injected = True
            interrupted = asyncio.get_running_loop().create_future()
            asyncio.get_running_loop().call_soon(interrupted.set_exception, cancelled)
            return interrupted
        return real_shield(task)

    def operation():
        entered.set()
        if not release.wait(5):
            raise RuntimeError("Test did not release failing worker")
        raise LookupError("PRIVATE_WORKER_DETAIL")

    monkeypatch.setattr(asyncio, "shield", first_cancellation)
    task = asyncio.create_task(run(operation))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        for _ in range(2):
            task.cancel("later cancellation")
            await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError) as raised:
            await asyncio.wait_for(task, 5)
        assert raised.value is cancelled
        assert cancelled.__notes__ == ["Existing caller note", f"{prefix}: LookupError"]
        assert all("PRIVATE_WORKER_DETAIL" not in note for note in cancelled.__notes__)
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)


@pytest.mark.asyncio
async def test_owned_thread_preserves_fatal_baseexception_behavior_during_drain(runner):
    run, _ = runner
    entered, release = Event(), Event()

    class FatalWorkerError(BaseException):
        pass

    failure = FatalWorkerError("Fatal worker identity")

    def operation():
        entered.set()
        if not release.wait(5):
            raise RuntimeError("Test did not release fatal worker")
        raise failure

    task = asyncio.create_task(run(operation))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel("cancel before fatal completion")
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(FatalWorkerError) as raised:
            await asyncio.wait_for(task, 5)
        assert raised.value is failure
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)


@pytest.mark.asyncio
async def test_meeting_wrapper_preserves_positional_and_keyword_argument_identity():
    from services.meetings.service import run_db

    positional, keyword, target_context = object(), object(), object()

    def operation(value, *, expected, failure_context):
        assert value is positional
        assert expected is keyword
        assert failure_context is target_context
        return expected

    assert (
        await run_db(
            operation, positional, expected=keyword, failure_context=target_context
        )
        is keyword
    )
