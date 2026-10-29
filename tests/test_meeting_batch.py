import asyncio
import json
from uuid import uuid4

import pytest

from services.db import get_connection
from services.graphs.runtime import dispatch
from services.jobs.models.execution import list_executions_for_job
from services.jobs.models.job import get_job
from services.jobs.scheduler import execute_job
from services.jobs.service import create_job_with_default_config, validate_input_params
from services.meetings import db, factory, service
from services.meetings.config import load_source_config
from services.meetings.types import MeetingProviderError
from tests.conftest import clean_meeting_rows
from tests.test_meeting_sync import Provider, note, state


@pytest.fixture
def sources(monkeypatch):
    suffix = uuid4().hex
    settings = {
        f"batch-{suffix}-{name}": {"provider": "test", "account_key": f"batch-{suffix}-{name}", "api_key_env": f"BATCH_{name.upper()}_KEY"}
        for name in ("a", "z")
    }
    monkeypatch.setenv("MEETING_SOURCES_JSON", json.dumps(settings))
    monkeypatch.setenv("BATCH_A_KEY", "test-credential")
    monkeypatch.setenv("BATCH_Z_KEY", "test-credential")
    configs = [load_source_config(name) for name in settings]
    yield configs
    for config in configs:
        clean_meeting_rows(config.account_key)


def providers(monkeypatch, sources, first=None):
    clients = {}

    def build(config):
        provider = first if config.name == sources[0].name and first is not None else Provider([note(text=f"Summary for {config.name}")])
        clients.setdefault(config.name, []).append(provider)
        return provider

    monkeypatch.setitem(factory._PROVIDER_BUILDERS, "test", build)
    return clients


@pytest.mark.asyncio
async def test_empty_graph_inputs_import_every_connection_and_replay_without_duplicates(sources, monkeypatch):
    clients = providers(monkeypatch, sources)
    validate_input_params({"graph_type": "meeting_ingest", "graph_inputs": {}, "timeout": 600})
    first = json.loads(await dispatch("meeting_ingest", {}))
    rows = [db.list_summaries(source=config.name)["items"][0] for config in sources]
    second = json.loads(await dispatch("meeting_ingest", {}))
    assert first["outcome"] == second["outcome"] == "completed"
    assert first["counts"]["created"] == second["counts"]["unchanged"] == 2
    assert [item["source"] for item in first["sources"]] == [config.name for config in sources]
    assert len({row["id"] for row in rows}) == 2
    assert {row["external_id"] for row in rows} == {"one"}
    assert all(db.get_summary(row["id"])["revision"] == 1 for row in rows)
    assert all(provider.closed for instances in clients.values() for provider in instances)
    assert "Summary for" not in json.dumps(first)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 429])
async def test_source_failure_does_not_block_other_connection_and_job_records_safe_outcomes(sources, monkeypatch, caplog, status_code):
    private = "private provider response and credential"

    class PartiallyFailingProvider(Provider):
        async def get_summary(self, external_id):
            if external_id == "two":
                raise MeetingProviderError(private, status_code)
            return await super().get_summary(external_id)

    failed = PartiallyFailingProvider([note(), note("two")])
    clients = providers(monkeypatch, sources, failed)
    params = {"graph_type": "meeting_ingest", "graph_inputs": {}, "timeout": 10}
    job_id = create_job_with_default_config("batch-job-" + uuid4().hex, {"minutes": 15}, params)
    try:
        result = await execute_job(get_job(job_id))
        report = json.loads(result["error"].split("MeetingSyncError: ", 1)[1])
        executions, total = list_executions_for_job(job_id)
        assert not result["success"] and executions[0]["status"] == "failed" and total == 1
        assert report["outcome"] == "failed" and report["counts"] is None
        assert report["known_counts"]["created"] == 1
        assert [item["outcome"] for item in report["sources"]] == ["failed", "completed"]
        assert report["sources"][0]["error_type"] == "MeetingProviderError"
        assert report["sources"][0]["status_code"] == status_code
        assert report["sources"][0]["counts"] is None
        assert private not in result["error"] and private not in caplog.text
        assert db.list_summaries(source=sources[0].name)["total"] == 1
        assert db.list_summaries(source=sources[1].name)["total"] == 1
        assert all(provider.closed for instances in clients.values() for provider in instances)
    finally:
        with get_connection() as conn, conn.cursor() as cursor:
            cursor.execute("DELETE FROM background_jobs WHERE id = %s", (job_id,))


@pytest.mark.asyncio
async def test_missing_connection_credential_does_not_prevent_other_imports(sources, monkeypatch):
    clients = providers(monkeypatch, sources)
    monkeypatch.delenv("BATCH_A_KEY")
    with pytest.raises(service.MeetingSyncError) as failed:
        await service.sync_sources()
    report = json.loads(str(failed.value))
    assert [item["outcome"] for item in report["sources"]] == ["failed", "completed"]
    assert report["sources"][0]["error_type"] == "ValueError"
    assert sources[0].name not in clients
    assert db.list_summaries(source=sources[1].name)["total"] == 1


@pytest.mark.asyncio
async def test_busy_connection_does_not_prevent_other_imports(sources, monkeypatch):
    providers(monkeypatch, sources)
    db.claim_source(sources[0], "another-device")
    try:
        result = await service.sync_sources()
        assert {item["source"]: item["outcome"] for item in result["sources"]} == {
            sources[0].name: "skipped_busy", sources[1].name: "completed",
        }
        assert result["counts"]["created"] == 1
        assert state(sources[0])["claim_owner"] == "another-device"
    finally:
        db.release_source(sources[0], "another-device", "continued")


@pytest.mark.asyncio
async def test_slow_first_connection_yields_time_for_later_connection_and_releases_claim(sources, monkeypatch):
    class SlowProvider(Provider):
        async def list_page(self, cursor=None):
            await asyncio.Event().wait()

    slow = SlowProvider([])
    providers(monkeypatch, sources, slow)
    result = await service.sync_sources(run_budget_seconds=2)
    assert result["outcome"] == "continued"
    assert [item["outcome"] for item in result["sources"]] == ["interrupted", "completed"]
    assert result["counts"] is None and result["known_counts"]["created"] == 1 and slow.closed
    assert state(sources[0])["claim_owner"] is None
    assert state(sources[0])["outcome"] == "interrupted"


@pytest.mark.asyncio
async def test_overall_deadline_includes_setup_and_cleanup_and_reports_deferred_sources(sources, monkeypatch):
    attempted = []

    async def slow_setup(source, **kwargs):
        attempted.append(source)
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.1)

    monkeypatch.setattr(service, "sync_source", slow_setup)
    result = await service.sync_sources(run_budget_seconds=0.05)
    assert attempted == [sources[0].name]
    assert [item["outcome"] for item in result["sources"]] == ["interrupted", "deferred"]
    assert result["outcome"] == "continued"


@pytest.mark.asyncio
async def test_next_run_prioritizes_previously_deferred_connection_after_slow_cleanup(sources, monkeypatch):
    class SlowCleanupProvider(Provider):
        async def list_page(self, cursor=None):
            await asyncio.Event().wait()

        async def aclose(self):
            await asyncio.sleep(0.6)
            await super().aclose()

    providers(monkeypatch, sources, SlowCleanupProvider([]))
    first = await service.sync_sources(run_budget_seconds=0.5)
    assert [item["outcome"] for item in first["sources"]] == ["interrupted", "deferred"]
    assert db.list_summaries(source=sources[1].name)["total"] == 0
    second = await service.sync_sources(run_budget_seconds=0.5)
    assert second["sources"][0]["source"] == sources[1].name
    assert second["sources"][0]["outcome"] == "completed"
    assert db.list_summaries(source=sources[1].name)["total"] == 1


@pytest.mark.asyncio
async def test_external_cancellation_stops_batch_and_releases_claim(sources, monkeypatch):
    entered = asyncio.Event()

    class SlowProvider(Provider):
        async def list_page(self, cursor=None):
            entered.set()
            await asyncio.Event().wait()

    first = SlowProvider([])
    clients = providers(monkeypatch, sources, first)
    task = asyncio.create_task(service.sync_sources())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert first.closed and sources[1].name not in clients
    assert state(sources[0])["outcome"] == "interrupted"
    assert db.claim_source(sources[0], "after-cancel") is not None
    db.release_source(sources[0], "after-cancel", "continued")


@pytest.mark.asyncio
async def test_batch_uses_one_config_snapshot(sources, monkeypatch):
    class ReconfiguringProvider(Provider):
        async def list_page(self, cursor=None):
            monkeypatch.setenv("MEETING_SOURCES_JSON", "{}")
            monkeypatch.delenv("BATCH_Z_KEY")
            return await super().list_page(cursor)

    providers(monkeypatch, sources, ReconfiguringProvider([note()]))
    result = await service.sync_sources()
    assert result["counts"]["created"] == 2
    assert result["outcome"] == "completed"


@pytest.mark.asyncio
async def test_no_connections_fails_instead_of_succeeding_without_imports(monkeypatch):
    monkeypatch.setenv("MEETING_SOURCES_JSON", "{}")
    with pytest.raises(ValueError, match="No meeting connections"):
        await service.sync_sources()
