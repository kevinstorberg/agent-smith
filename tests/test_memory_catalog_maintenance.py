from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pinecone.openapi_support.api_client import ApiClient

from scripts import memory_catalog
from services.db import get_connection
from services.memory import catalog, db, maintenance
from services.memory.backends import pinecone_backend as backend


class Provider:
    def __init__(self, count=3):
        self.ids = [str(UUID(int=number + 1)) for number in range(count)]
        self.calls = []
        self.missing = set()
        self.error = None

    def list_paginated(self, **kwargs):
        self.calls.append(("list", kwargs))
        if self.error:
            raise self.error
        start = int(kwargs["pagination_token"] or 0)
        end = start + kwargs["limit"]
        page = {"vectors": [{"id": id} for id in self.ids[start:end]]}
        if end < len(self.ids):
            page["pagination"] = {"next": str(end)}
        return page

    def fetch(self, *, ids, **kwargs):
        self.calls.append(("fetch", {"ids": ids, **kwargs}))
        if self.error:
            raise self.error
        return {
            "vectors": {
                id: {
                    "metadata": {
                        "text": "sensitive-memory-body-never-print",
                        "repo": "project",
                        "tags": '["keep"]',
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                }
                for id in ids
                if id not in self.missing
            }
        }

    def __getattr__(self, name):
        pytest.fail(f"Maintenance attempted unexpected provider operation: {name}")


@pytest.fixture
def source():
    value = catalog.Source(f"test-maintenance-{uuid4().hex}")
    yield value
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM memory_catalog_sources WHERE source_key=%s", (value.key,)
        )


@pytest.fixture
def runtime(monkeypatch, source):
    provider = Provider()
    opened = []

    @contextmanager
    def open_index(actual_source, budget):
        assert actual_source == source
        budget.request()
        opened.append(actual_source)
        yield provider

    monkeypatch.setattr(maintenance, "open_index", open_index)
    components = SimpleNamespace(
        catalog=catalog,
        maintenance=maintenance,
        source=source,
        project=db.catalog_metadata,
    )
    monkeypatch.setattr(memory_catalog, "_components", lambda: components)
    monkeypatch.setattr(
        db, "_get_embeddings", lambda: pytest.fail("Maintenance loaded embeddings")
    )
    monkeypatch.setattr(
        db, "_get_retriever", lambda: pytest.fail("Maintenance initialized a retriever")
    )
    return SimpleNamespace(
        provider=provider, opened=opened, source=source, components=components
    )


def arguments(source, command="initialize", *, count=3, requests=20, records=20000):
    result = [
        command,
        "--confirm-index",
        source.index_name,
        "--confirm-namespace",
        "__default__",
        "--confirm-quiescent-writers",
    ]
    if command == "abort-build":
        return [*result, "--confirm-initializer-stopped"]
    result += [
        "--max-records",
        str(records),
        "--max-requests",
        str(requests),
        "--deadline-seconds",
        "60",
    ]
    if command == "initialize":
        result += ["--expected-count", str(count)]
    return result


def output(capsys):
    captured = capsys.readouterr()
    assert "sensitive-memory-body" not in captured.out + captured.err
    return [json.loads(line) for line in captured.out.splitlines()]


def ready(source):
    build = catalog.begin_build(source, expected_count=0)
    catalog.finish_build(build)


def test_explicit_initializer_streams_over_ten_thousand_and_publishes_exact_count(
    runtime, capsys
):
    runtime.provider.ids = [str(UUID(int=number + 1)) for number in range(10001)]
    assert (
        memory_catalog.main(arguments(runtime.source, count=10001, requests=203)) == 0
    )

    reports = output(capsys)
    assert [report["stage"] for report in reports] == ["building", "ready"]
    assert reports[-1]["records"] == 10001
    assert reports[-1]["requests"] == 203
    page = catalog.select_page(runtime.source, limit=10, offset=9990)
    assert page.total == 10001
    assert len(page.ids) == 10
    assert len(runtime.opened) == 1
    assert len(runtime.provider.calls) == 202
    assert all(
        len(call["ids"]) <= 100
        for kind, call in runtime.provider.calls
        if kind == "fetch"
    )


@pytest.mark.parametrize("count", [2, 4])
def test_wrong_expected_count_never_publishes_partial_catalog(runtime, capsys, count):
    assert memory_catalog.main(arguments(runtime.source, count=count)) == 1
    assert output(capsys)[-1]["stage"] == "failed"
    with pytest.raises(catalog.Unavailable, match="failed"):
        catalog.select_page(runtime.source)


def test_provider_error_preserves_failed_state_without_content_or_secret_output(
    runtime, capsys
):
    runtime.provider.error = RuntimeError("sensitive-memory-body-and-secret-key")
    assert memory_catalog.main(arguments(runtime.source)) == 1
    assert output(capsys)[-1]["reason"] == "maintenance_failed"
    with pytest.raises(catalog.Unavailable, match="failed"):
        catalog.select_page(runtime.source)
    assert len(runtime.provider.calls) == 1


def test_empty_initialization_is_explicit_and_does_not_fetch(runtime, capsys):
    runtime.provider.ids = []
    assert memory_catalog.main(arguments(runtime.source, count=0)) == 0
    assert output(capsys)[-1]["records"] == 0
    assert [kind for kind, _ in runtime.provider.calls] == ["list"]


def test_request_budget_includes_discovery_and_prevents_fetch(runtime, capsys):
    assert memory_catalog.main(arguments(runtime.source, requests=2)) == 1
    report = output(capsys)[-1]
    assert report["reason"] == "budget_exceeded"
    assert report["requests"] == 2
    assert [kind for kind, _ in runtime.provider.calls] == ["list"]


def test_record_budget_limits_provider_list_size_before_fetch(runtime, capsys):
    assert memory_catalog.main(arguments(runtime.source, count=1, records=1)) == 1
    report = output(capsys)[-1]
    assert report["reason"] == "budget_exceeded"
    assert len(runtime.provider.calls) == 2
    assert runtime.provider.calls[0][1]["limit"] == 1
    assert runtime.provider.calls[1][1]["ids"] == runtime.provider.ids[:1]
    with pytest.raises(catalog.Unavailable, match="failed"):
        catalog.select_page(runtime.source)


@pytest.mark.parametrize(
    "field,value",
    [
        ("--max-records", "0"),
        ("--max-requests", "-1"),
        ("--deadline-seconds", "nan"),
        ("--deadline-seconds", "inf"),
        ("--deadline-seconds", "0"),
    ],
)
def test_invalid_budget_fails_before_configuration_or_any_io(monkeypatch, field, value):
    monkeypatch.setattr(
        memory_catalog, "_components", lambda: pytest.fail("Loaded config")
    )
    args = arguments(catalog.Source("test"))
    args[args.index(field) + 1] = value
    with pytest.raises(SystemExit) as error:
        memory_catalog.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "change", ["index", "namespace", "expected", "duplicate", "repair-budget"]
)
def test_source_and_record_confirmations_fail_before_catalog_or_provider_io(
    runtime, monkeypatch, capsys, change
):
    args = arguments(runtime.source)
    if change == "index":
        args[args.index("--confirm-index") + 1] = "wrong-index"
    elif change == "namespace":
        args[args.index("--confirm-namespace") + 1] = "wrong-namespace"
    elif change == "expected":
        args[args.index("--expected-count") + 1] = "20001"
    else:
        args = arguments(runtime.source, "repair", records=1)
        args += [
            "--id",
            runtime.provider.ids[0],
            "--id",
            runtime.provider.ids[0 if change == "duplicate" else 1],
        ]
    monkeypatch.setattr(catalog, "_cursor", lambda: pytest.fail("Catalog accessed"))
    assert memory_catalog.main(args) == 1
    assert not runtime.provider.calls and not runtime.opened
    assert not capsys.readouterr().out


def test_dry_run_performs_no_sql_or_provider_io(runtime, monkeypatch, capsys):
    monkeypatch.setattr(catalog, "_cursor", lambda: pytest.fail("Catalog accessed"))
    assert memory_catalog.main([*arguments(runtime.source), "--dry-run"]) == 0
    assert output(capsys)[0]["stage"] == "validated"
    assert not runtime.provider.calls and not runtime.opened


def test_initialization_with_pending_writer_fails_before_provider_io(runtime, capsys):
    ready(runtime.source)
    catalog.begin_mutation(runtime.source, runtime.provider.ids[0], kind="delete")
    assert memory_catalog.main(arguments(runtime.source)) == 1
    assert output(capsys)[-1]["reason"] == "catalog_conflict"
    assert not runtime.provider.calls and not runtime.opened
    assert len(catalog.pending(runtime.source)) == 1


@pytest.mark.parametrize("deleted", [False, True])
def test_unacknowledged_repair_reads_only_known_id_then_applies_actual_state(
    runtime, capsys, deleted
):
    ready(runtime.source)
    id = runtime.provider.ids[0]
    original = catalog.begin_mutation(runtime.source, id, kind="delete")
    if deleted:
        runtime.provider.missing.add(id)
    assert (
        memory_catalog.main(
            [*arguments(runtime.source, "repair", requests=2, records=1), "--id", id]
        )
        == 0
    )
    assert output(capsys)[-1]["stage"] == "repaired"
    assert len(runtime.provider.calls) == 1
    kind, call = runtime.provider.calls[0]
    assert kind == "fetch" and call["ids"] == [id]
    assert catalog.select_page(runtime.source).total == (0 if deleted else 1)
    assert catalog.pending(runtime.source) == []
    with pytest.raises(catalog.Conflict, match="token changed"):
        replacement = catalog.begin_mutation(runtime.source, id, kind="delete")
        try:
            catalog.acknowledge(original, None)
        finally:
            catalog.acknowledge(replacement, None)
            catalog.finalize(replacement)


def test_acknowledged_repair_finalizes_without_opening_provider(runtime, capsys):
    ready(runtime.source)
    id = runtime.provider.ids[0]
    mutation = catalog.begin_mutation(runtime.source, id, kind="upsert")
    catalog.acknowledge(mutation, {"id": id, "repo": "kept", "tags": []})
    assert (
        memory_catalog.main(
            [*arguments(runtime.source, "repair", requests=1, records=1), "--id", id]
        )
        == 0
    )
    assert output(capsys)[-1]["requests"] == 0
    assert not runtime.opened and not runtime.provider.calls
    assert catalog.select_page(runtime.source, repo="kept").total == 1


def test_repair_failure_retains_pending_without_retry(runtime, capsys):
    ready(runtime.source)
    id = runtime.provider.ids[0]
    catalog.begin_mutation(runtime.source, id, kind="delete")
    runtime.provider.error = RuntimeError("sensitive-memory-body")
    assert memory_catalog.main([*arguments(runtime.source, "repair"), "--id", id]) == 1
    assert output(capsys)[-1]["stage"] == "failed"
    assert len(runtime.provider.calls) == 1
    assert len(catalog.pending(runtime.source)) == 1
    with pytest.raises(catalog.Unavailable, match="unresolved"):
        catalog.select_page(runtime.source)


@pytest.mark.parametrize("deleted", [False, True])
def test_explicit_known_id_repairs_external_drift_without_preexisting_pending(
    runtime, capsys, deleted
):
    ready(runtime.source)
    id = runtime.provider.ids[0]
    if deleted:
        catalog.write_through(
            runtime.source,
            id,
            kind="upsert",
            metadata={"id": id, "tags": []},
            operation=lambda: None,
        )
        runtime.provider.missing.add(id)
    assert catalog.pending(runtime.source) == []
    assert (
        memory_catalog.main(
            [*arguments(runtime.source, "repair", requests=2, records=1), "--id", id]
        )
        == 0
    )
    assert output(capsys)[-1]["stage"] == "repaired"
    assert len(runtime.provider.calls) == 1
    assert runtime.provider.calls[0][0] == "fetch"
    assert runtime.provider.calls[0][1]["ids"] == [id]
    assert catalog.select_page(runtime.source).total == (0 if deleted else 1)
    assert catalog.pending(runtime.source) == []


def test_explicit_abort_requires_stopped_initializer_and_performs_sql_only(
    runtime, capsys
):
    catalog.begin_build(runtime.source, expected_count=3)
    args = arguments(runtime.source, "abort-build")
    with pytest.raises(SystemExit):
        memory_catalog.main(args[:-1])
    capsys.readouterr()
    assert memory_catalog.main(args) == 0
    report = output(capsys)[-1]
    assert report["stage"] == "aborted" and report["requests"] == 0
    assert not runtime.opened and not runtime.provider.calls
    with pytest.raises(catalog.Unavailable, match="failed"):
        catalog.select_page(runtime.source)


def test_real_sdk_opener_constructs_bounded_requests_without_network(monkeypatch):
    calls = []
    events = []
    source = catalog.Source("test-real-sdk-transport")
    id = str(UUID(int=1))

    def call_api(client, path, method, **kwargs):
        calls.append((path, method, kwargs))
        assert client.configuration.retries == 0
        assert 0 < kwargs["_request_timeout"] <= 10
        if path == "/indexes/{index_name}":
            assert kwargs["path_params"] == {"index_name": source.index_name}
            return {"host": "test-real-sdk.svc.test.pinecone.io"}
        if path == "/vectors/list":
            return {"vectors": [{"id": id}]}
        if path == "/vectors/fetch":
            return SimpleNamespace(
                namespace="",
                vectors={id: {"id": id, "values": [0.1], "metadata": {"repo": "test"}}},
                usage=None,
            )
        pytest.fail(f"Unexpected SDK operation: {path}")

    monkeypatch.setattr(ApiClient, "call_api", call_api)
    monkeypatch.setenv("PINECONE_API_KEY", "fake-not-for-output")
    monkeypatch.setattr(
        backend.BillableEvent,
        "start",
        lambda provider, operation, **metadata: (
            events.append((operation, metadata))
            or SimpleNamespace(finish=lambda *a, **k: None)
        ),
    )
    budget = maintenance.MaintenanceBudget(1, 3, 20)
    with maintenance.open_index(source, budget) as index:
        rows = list(maintenance.iter_rows(index, budget))
    assert rows == [[{"id": id, "text": "", "metadata": {"repo": "test"}}]]
    assert budget.records == 1 and budget.requests == 3
    assert [method for _, method, _ in calls] == ["GET", "GET", "GET"]
    assert [event[0] for event in events] == [
        "describe_index",
        "list_paginated",
        "fetch",
    ]
    assert all(metadata["index"] == source.index_name for _, metadata in events)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_records": 0},
        {"max_requests": True},
        {"deadline_seconds": float("inf")},
        {"deadline_seconds": -1},
    ],
)
def test_budget_rejects_invalid_internal_values(kwargs):
    values = {"max_records": 1, "max_requests": 1, "deadline_seconds": 1}
    values.update(kwargs)
    with pytest.raises(ValueError):
        maintenance.MaintenanceBudget(**values)


def test_expired_budget_stops_before_first_provider_request(monkeypatch):
    clock = [0.0]
    budget = maintenance.MaintenanceBudget(1, 2, 1, clock=lambda: clock[0])
    clock[0] = 2
    provider = Provider(1)
    with pytest.raises(TimeoutError):
        list(maintenance.iter_rows(provider, budget))
    assert provider.calls == [] and budget.requests == 0


def test_strict_initializer_rejects_missing_records_before_publishing():
    provider = Provider(1)
    provider.missing = set(provider.ids)
    with pytest.raises(RuntimeError, match="incomplete page"):
        list(maintenance.iter_rows(provider, maintenance.MaintenanceBudget(2, 3, 30)))
    assert [kind for kind, _ in provider.calls] == ["list", "fetch"]


@pytest.mark.parametrize("duplicate", ["id", "cursor"])
def test_strict_initializer_rejects_repeated_provider_state_before_fetching_it(
    duplicate,
):
    provider = Provider(1)
    id = provider.ids[0]
    list_calls = []

    def list_page(**kwargs):
        list_calls.append(kwargs)
        if len(list_calls) == 1:
            return {"vectors": [{"id": id}], "pagination": {"next": "again"}}
        return {
            "vectors": [{"id": id if duplicate == "id" else str(UUID(int=2))}],
            "pagination": {"next": "again"},
        }

    provider.list_paginated = list_page
    with pytest.raises(RuntimeError, match="repeated"):
        list(maintenance.iter_rows(provider, maintenance.MaintenanceBudget(3, 5, 30)))
    assert len(list_calls) == 2
    assert len(provider.calls) == 1
