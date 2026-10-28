import asyncio
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

import services.jobs.scheduler as scheduler_module
from services.config import DEVICE_NAME
from services.db import get_connection
from services.jobs.models.config import JobConfigModel, create_config, list_configs
from services.jobs.models.execution import list_executions_for_job
from services.jobs.models.job import create_job, get_job, get_job_by_name
from services.jobs.scheduler import JobScheduler
from services.jobs.scoping import job_runs_on_device
from services.meetings import db, digestion_db, factory
from services.meetings.config import load_source_config
from services.meetings.schedule import configure_schedule
from services.meetings.types import MeetingSummary, NotePage, NoteReference, TranscriptPage, TranscriptSegment
from tests.conftest import clean_meeting_rows


@pytest.fixture
def source(monkeypatch):
    name, account = "schedule-" + uuid4().hex, "account-" + uuid4().hex
    monkeypatch.setenv("MEETING_SOURCES_JSON", json.dumps({name: {
        "provider": "test", "account_key": account, "api_key_env": "MEETING_SCHEDULE_TEST_KEY",
    }}))
    monkeypatch.setenv("MEETING_SCHEDULE_TEST_KEY", "not-a-real-credential")
    config = load_source_config(name)
    yield config
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM background_jobs WHERE name = %s", ("Meetings: " + name,))
    clean_meeting_rows(account)


def test_schedule_is_idempotent_and_explicitly_scoped_to_one_device(source):
    job_id = configure_schedule(source.name, "meeting-device")
    assert configure_schedule(source.name, "meeting-device") == job_id
    job = get_job(job_id)
    assert job["name"] == "Meetings: " + source.name
    assert job["schedule_config"] == {"minutes": 15}
    assert job["input_params"] == {"graph_type": "meeting_ingest", "graph_inputs": {"source": source.name}, "timeout": 600}
    configs = list_configs(job_id)
    assert len(configs) == 1
    assert configs[0]["device"] == "meeting-device"
    assert configs[0]["repo"] == "*"
    assert configs[0]["enabled"] and not configs[0]["exclude"]
    assert job_runs_on_device(job_id, "meeting-device")
    assert not job_runs_on_device(job_id, "other-device")


def test_reconfigure_updates_interval_and_replaces_previous_deployment_scopes(source):
    job_id = configure_schedule(source.name, "old-device")
    create_config(job_id, device="*", repo="legacy-project")
    assert configure_schedule(source.name, "new-device", interval_minutes=7.5) == job_id
    assert get_job(job_id)["schedule_config"] == {"minutes": 7.5}
    configs = list_configs(job_id)
    assert len(configs) == 1
    assert configs[0]["device"] == "new-device"
    assert not job_runs_on_device(job_id, "old-device")
    assert job_runs_on_device(job_id, "new-device")


@pytest.mark.parametrize("device", ["", " ", "*", None])
def test_schedule_rejects_missing_or_wildcard_device(source, device):
    with pytest.raises(ValueError):
        configure_schedule(source.name, device)
    assert get_job_by_name("Meetings: " + source.name) is None


@pytest.mark.parametrize("interval", [0, -1, True, math.inf, math.nan])
def test_schedule_rejects_invalid_intervals(source, interval):
    with pytest.raises(ValueError):
        configure_schedule(source.name, "meeting-device", interval_minutes=interval)
    assert get_job_by_name("Meetings: " + source.name) is None


def test_schedule_rejects_unknown_source_before_writing(source):
    with pytest.raises(ValueError):
        configure_schedule("unknown-meeting-source", "meeting-device")
    assert get_job_by_name("Meetings: unknown-meeting-source") is None


@pytest.mark.parametrize("params", [{"command": "echo unrelated"}, {"graph_type": "meeting_ingest", "graph_inputs": {"source": "another-source"}, "timeout": 300}])
def test_schedule_does_not_overwrite_unrelated_job_with_same_name(source, params):
    job_id = create_job("Meetings: " + source.name, {"hours": 1}, params)
    with pytest.raises(ValueError):
        configure_schedule(source.name, "meeting-device")
    assert get_job(job_id)["input_params"] == params
    assert get_job(job_id)["schedule_config"] == {"hours": 1}
    assert list_configs(job_id) == []


def test_new_job_and_its_device_scope_commit_atomically(source, monkeypatch):
    def failed_config(*args, **kwargs):
        raise RuntimeError("Device configuration failed")

    monkeypatch.setattr(JobConfigModel, "create", failed_config)
    with pytest.raises(RuntimeError, match="Device configuration failed"):
        configure_schedule(source.name, "meeting-device")
    assert get_job_by_name("Meetings: " + source.name) is None


def test_concurrent_configuration_creates_one_job_and_one_device_scope(source):
    barrier = threading.Barrier(2)

    def configure():
        barrier.wait(timeout=5)
        return configure_schedule(source.name, "meeting-device")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: configure(), range(2)))
    assert first == second
    assert len(list_configs(first)) == 1


@pytest.mark.asyncio
async def test_fifteen_minute_schedule_fires_twice_and_restart_uses_actual_history(source, monkeypatch):
    stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    summary = MeetingSummary("scheduled-note", "A scheduled meeting", "A durable decision", None, "https://example.test/note", stamp, stamp)
    providers = []

    class Provider:
        closed = False

        def __init__(self, config):
            self.get_calls = []
            providers.append(self)

        async def list_page(self, cursor=None):
            return NotePage((NoteReference(summary.external_id, stamp),))

        async def get_summary(self, external_id):
            self.get_calls.append(external_id)
            return summary

        async def aclose(self):
            self.closed = True

        async def get_transcript_page(self, external_id, cursor=None):
            return TranscriptPage((TranscriptSegment("A durable decision", {}),))

    monkeypatch.setitem(factory._PROVIDER_BUILDERS, "test", Provider)
    from services.meetings import analysis

    async def no_new_memories(*args, **kwargs):
        return {"items": [], "reason": "No new durable information"}

    monkeypatch.setattr(analysis, "analyze_memories", no_new_memories)
    job_id = configure_schedule(source.name, DEVICE_NAME)
    clock = {"now": datetime.now(timezone.utc)}
    monkeypatch.setattr(scheduler_module, "_utcnow", lambda: clock["now"])
    scheduler = JobScheduler(device_name=DEVICE_NAME)
    await scheduler._seed_schedule()
    await scheduler._tick()
    assert list_executions_for_job(job_id)[1] == 0
    first_id = None
    for _ in range(2):
        clock["now"] += timedelta(minutes=15)
        await scheduler._tick()
        await asyncio.wait_for(asyncio.gather(*list(scheduler._inflight)), 5)
        rows = db.list_summaries(source=source.name)["items"]
        assert len(rows) == 1
        assert rows[0]["revision"] == 1
        first_id = first_id or rows[0]["id"]
        assert rows[0]["id"] == first_id
        assert db.get_summary(first_id)["summary_text"] == summary.summary_text
    executions, total = list_executions_for_job(job_id)
    assert total == 2
    assert all(row["status"] == "success" for row in executions)
    assert all(row["device"] == DEVICE_NAME for row in executions)
    assert len(providers) == 3 and all(provider.closed for provider in providers)
    assert providers[0].get_calls == [summary.external_id]
    assert providers[1].get_calls == [summary.external_id, summary.external_id]
    assert providers[2].get_calls == []
    assert digestion_db.get_transcript(first_id)["status"] == "ready"
    assert get_job(job_id)["schedule_config"] == {"minutes": 15}
    last_started = datetime.fromisoformat(executions[0]["started_at"])
    restarted = JobScheduler(device_name=DEVICE_NAME)
    clock["now"] = last_started + timedelta(minutes=5)
    await restarted._seed_schedule()
    assert restarted._next_run[job_id] == last_started + timedelta(minutes=15)
    clock["now"] = last_started + timedelta(minutes=20)
    await restarted._seed_schedule()
    assert restarted._next_run[job_id] == clock["now"]


@pytest.mark.asyncio
async def test_scheduler_shutdown_interrupts_meeting_graph_and_releases_source_claim(source, monkeypatch):
    entered = asyncio.Event()
    providers = []

    class WaitingProvider:
        closed = False

        def __init__(self, config):
            providers.append(self)

        async def list_page(self, cursor=None):
            entered.set()
            await asyncio.Event().wait()

        async def get_summary(self, external_id):
            raise AssertionError("Blocked listing cannot produce a summary")

        async def aclose(self):
            self.closed = True

    monkeypatch.setitem(factory._PROVIDER_BUILDERS, "test", WaitingProvider)
    job_id = configure_schedule(source.name, DEVICE_NAME)
    clock = {"now": datetime.now(timezone.utc)}
    monkeypatch.setattr(scheduler_module, "_utcnow", lambda: clock["now"])
    scheduler = JobScheduler(poll_interval=0.05, device_name=DEVICE_NAME)
    await scheduler.start()
    try:
        clock["now"] += timedelta(minutes=15)
        await scheduler._tick()
        await asyncio.wait_for(entered.wait(), 5)
    finally:
        await asyncio.wait_for(scheduler.stop(), 5)
    executions, total = list_executions_for_job(job_id)
    assert total == 1
    assert executions[0]["status"] == "interrupted"
    assert executions[0]["completed_at"] is not None
    assert providers[0].closed
    assert db.source_status(source.name)[0]["outcome"] == "interrupted"
    assert db.claim_source(source, "after-shutdown") is not None
    db.release_source(source, "after-shutdown", "continued")
