from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from psycopg2.extras import execute_values

from services.db import get_connection
from services.memory import catalog


@pytest.fixture
def source():
    value = catalog.Source(f"test-catalog-{uuid4().hex}")
    yield value
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM memory_catalog_sources WHERE source_key=%s", (value.key,)
        )


def seed(source, count=10051):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO memory_catalog_sources(source_key,status) VALUES(%s,'ready')",
            (source.key,),
        )
        execute_values(
            cursor,
            """INSERT INTO memory_catalog_entries
            (source_key,id,repo,tags,source_type,created_at,updated_at) VALUES %s""",
            [
                (
                    source.key,
                    str(UUID(int=number + 1)),
                    "project" if number % 3 == 0 else "other",
                    ["keep"] if number % 5 == 0 else [],
                    "meeting" if number % 7 == 0 else "general",
                    base + timedelta(seconds=number),
                    base + timedelta(seconds=count - number),
                )
                for number in range(count)
            ],
        )


@pytest.mark.parametrize(
    "sort,reverse",
    [
        ("created_at_asc", False),
        ("created_at_desc", True),
        ("updated_at_asc", True),
        ("updated_at_desc", False),
    ],
)
def test_sql_pages_return_only_requested_ids_across_full_global_sorts(
    source, sort, reverse
):
    seed(source)
    ids = [str(UUID(int=number + 1)) for number in range(10051)]
    if reverse:
        ids.reverse()
    first = catalog.select_page(source, sort=sort, limit=10)
    deep = catalog.select_page(source, sort=sort, limit=10, offset=10040)
    empty = catalog.select_page(source, sort=sort, limit=10, offset=10051)

    assert first.total == deep.total == empty.total == 10051
    assert first.ids == ids[:10]
    assert deep.ids == ids[10040:10050]
    assert empty.ids == []
    assert len(first.context_tags) == len(deep.context_tags) == 10
    catalog.check_page(source, first.generation)


def test_sql_filters_and_lookback_apply_before_count_and_page(source):
    seed(source)
    expected = [
        str(UUID(int=number + 1))
        for number in range(10051)
        if number % 105 == 0 and number <= 550
    ]
    page = catalog.select_page(
        source,
        repo="project",
        tags=["keep"],
        meeting_only=True,
        sort="created_at_asc",
        limit=2,
        offset=2,
        changed_after=datetime(2026, 1, 1, tzinfo=timezone.utc)
        + timedelta(seconds=9501),
    )
    assert page.total == len(expected)
    assert page.ids == expected[2:4]


@pytest.mark.parametrize("status", [None, "empty", "building", "failed"])
def test_missing_or_incomplete_index_is_unavailable(source, status):
    if status is not None:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO memory_catalog_sources(source_key,status) VALUES(%s,%s)",
                (source.key, status),
            )
    with pytest.raises(catalog.Unavailable):
        catalog.select_page(source, limit=10)
    with pytest.raises(catalog.Unavailable):
        catalog.check_page(source, 0)


def test_pending_write_and_generation_drift_fail_closed(source):
    seed(source, 3)
    page = catalog.select_page(source, limit=1)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO memory_catalog_pending(source_key,id,operation_token,kind)
            VALUES(%s,%s,%s,'upsert')""",
            (source.key, str(UUID(int=1)), str(uuid4())),
        )
    with pytest.raises(catalog.Unavailable, match="unresolved writes"):
        catalog.select_page(source)
    with pytest.raises(catalog.Unavailable, match="unresolved writes"):
        catalog.check_page(source, page.generation)
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM memory_catalog_pending WHERE source_key=%s", (source.key,)
        )
        cursor.execute(
            "UPDATE memory_catalog_sources SET generation=generation+1 WHERE source_key=%s",
            (source.key,),
        )
    with pytest.raises(catalog.Unavailable, match="changed while"):
        catalog.check_page(source, page.generation)


def test_namespace_and_index_identity_do_not_share_listing_state(source):
    seed(source, 3)
    assert catalog.select_page(source, repo="").total == 3
    for other in [
        catalog.Source(source.index_name, "different"),
        catalog.Source("other-index"),
    ]:
        with pytest.raises(catalog.Unavailable, match="not initialized"):
            catalog.select_page(other)
    assert catalog.Source(source.index_name, "__default__").key == source.key


def test_catalog_schema_has_no_content_vector_or_access_timestamp_columns():
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name='memory_catalog_entries'"
        )
        columns = {row[0] for row in cursor.fetchall()}
    assert columns == {
        "source_key",
        "catalog_version",
        "id",
        "repo",
        "tags",
        "source_type",
        "source_id",
        "meeting_id",
        "created_at",
        "updated_at",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"offset": -1},
        {"sort": "unsafe"},
        {"tags": "tag"},
        {"meeting_only": 1},
        {"changed_after": datetime(2026, 1, 1)},
    ],
)
def test_invalid_page_inputs_fail_before_database_io(source, monkeypatch, kwargs):
    def forbidden():
        raise AssertionError("Invalid input reached database")

    monkeypatch.setattr(catalog, "get_connection", forbidden)
    with pytest.raises(ValueError):
        catalog.select_page(source, **kwargs)


def metadata(id, **changes):
    return {
        "id": id,
        "repo": "changed",
        "tags": ["critical"],
        "source_type": "general",
        "source_id": id,
        "created_at": "2027-01-01T00:00:00+00:00",
        "updated_at": "2027-01-01T00:00:00+00:00",
        **changes,
    }


def test_write_through_releases_sql_connection_before_provider_and_updates_listing(
    source, monkeypatch
):
    from contextlib import contextmanager

    seed(source, 3)
    active = [0]
    original = catalog.get_connection

    @contextmanager
    def tracked():
        with original() as connection:
            active[0] += 1
            try:
                yield connection
            finally:
                active[0] -= 1

    monkeypatch.setattr(catalog, "get_connection", tracked)
    id = str(uuid4())
    calls = []

    def write():
        assert active[0] == 0
        calls.append("upsert")
        assert [item.id for item in catalog.pending(source)] == [id]
        with pytest.raises(catalog.Unavailable, match="unresolved writes"):
            catalog.select_page(source)
        return "acknowledged"

    assert (
        catalog.write_through(
            source, id, kind="upsert", metadata=metadata(id), operation=write
        )
        == "acknowledged"
    )
    assert calls == ["upsert"]
    assert catalog.select_page(source, tags=["critical"]).ids == [id]
    assert catalog.select_page(source).total == 4
    assert catalog.pending(source) == []

    def delete():
        assert active[0] == 0
        calls.append("delete")

    catalog.write_through(source, id, kind="delete", metadata=None, operation=delete)
    assert calls == ["upsert", "delete"]
    assert catalog.select_page(source).total == 3


def test_uncertain_provider_failure_retains_pending_and_blocks_same_id_before_provider(
    source,
):
    seed(source, 3)
    id = str(UUID(int=1))
    calls = []

    def fail():
        calls.append("provider")
        raise RuntimeError("Synthetic uncertain provider failure")

    with pytest.raises(RuntimeError, match="uncertain provider"):
        catalog.write_through(
            source, id, kind="upsert", metadata=metadata(id), operation=fail
        )
    with pytest.raises(catalog.Conflict):
        catalog.write_through(
            source,
            id,
            kind="delete",
            metadata=None,
            operation=lambda: calls.append("wrong"),
        )
    assert calls == ["provider"]
    assert (
        len(catalog.pending(source)) == 1
        and not catalog.pending(source)[0].acknowledged
    )
    with pytest.raises(catalog.Unavailable, match="unresolved writes"):
        catalog.select_page(source)


def test_acknowledgement_is_durable_and_finalization_is_idempotent(source, monkeypatch):
    seed(source, 1)
    id = str(uuid4())
    original = catalog.finalize
    calls = []

    def fail_finalize(mutation):
        raise catalog.Unavailable("Synthetic SQL finalization failure")

    monkeypatch.setattr(catalog, "finalize", fail_finalize)
    payload = metadata(
        id,
        content="DO NOT COPY",
        text="DO NOT COPY",
        vector=[1.0],
        values=[1.0],
        last_accessed_at="2030-01-01T00:00:00+00:00",
    )
    with pytest.raises(catalog.Unavailable, match="finalization"):
        catalog.write_through(
            source,
            id,
            kind="upsert",
            metadata=payload,
            operation=lambda: calls.append("provider"),
        )
    mutation = catalog.pending(source)[0]
    assert mutation.acknowledged and calls == ["provider"]
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT projection FROM memory_catalog_pending WHERE source_key=%s",
            (source.key,),
        )
        projection = cursor.fetchone()[0]
    assert set(projection) == set(catalog._ENTRY_FIELDS)
    monkeypatch.setattr(catalog, "finalize", original)
    claimed = catalog.claim_repair(source, id, quiescent=True)
    assert claimed.acknowledged
    catalog.finalize(claimed)
    page = catalog.select_page(source)
    catalog.finalize(claimed)
    catalog.check_page(source, page.generation)
    assert page.total == 2 and calls == ["provider"]


def test_explicit_known_id_repair_replaces_token_and_uses_actual_presence(source):
    seed(source, 1)
    id = str(UUID(int=1))
    original = catalog.begin_mutation(source, id, kind="delete")
    with pytest.raises(ValueError, match="quiescent"):
        catalog.claim_repair(source, id, quiescent=False)
    repaired = catalog.claim_repair(source, id, quiescent=True)
    assert repaired.token != original.token
    with pytest.raises(catalog.Conflict, match="token changed"):
        catalog.acknowledge(original, None)
    catalog.acknowledge(repaired, metadata(id))
    catalog.finalize(repaired)
    assert catalog.select_page(source, tags=["critical"]).ids == [id]
    deletion = catalog.begin_mutation(source, id, kind="upsert")
    catalog.acknowledge(deletion, None)
    catalog.finalize(deletion)
    assert catalog.select_page(source).total == 0


def test_writes_do_not_turn_an_uninitialized_source_ready(source):
    id = str(uuid4())
    catalog.write_through(
        source, id, kind="upsert", metadata=metadata(id), operation=lambda: None
    )
    assert catalog.pending(source) == []
    with pytest.raises(catalog.Unavailable, match="not initialized"):
        catalog.select_page(source)


def test_same_id_concurrent_write_fails_without_invoking_second_provider(source):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    seed(source, 1)
    id = str(UUID(int=1))
    entered, release = Event(), Event()
    calls = []

    def paused():
        calls.append("first")
        entered.set()
        assert release.wait(5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            catalog.write_through,
            source,
            id,
            kind="upsert",
            metadata=metadata(id),
            operation=paused,
        )
        try:
            assert entered.wait(5)
            second = pool.submit(
                catalog.write_through,
                source,
                id,
                kind="delete",
                metadata=None,
                operation=lambda: calls.append("second"),
            )
            with pytest.raises(catalog.Conflict):
                second.result(timeout=3)
        finally:
            release.set()
        first.result(timeout=5)
    assert calls == ["first"]
    assert catalog.select_page(source).total == 1


def test_explicit_build_gates_writes_and_publishes_only_complete_staged_version(source):
    seed(source, 3)
    build = catalog.begin_build(source, expected_count=2)
    ids = [str(uuid4()), str(uuid4())]
    catalog.stage_build(build, [metadata(ids[0])])
    with pytest.raises(catalog.Unavailable, match="building"):
        catalog.select_page(source)
    with pytest.raises(catalog.Unavailable, match="blocked"):
        catalog.write_through(
            source,
            ids[1],
            kind="upsert",
            metadata=metadata(ids[1]),
            operation=lambda: pytest.fail("BUILDING reached provider"),
        )
    with pytest.raises(catalog.Conflict, match="count differs"):
        catalog.finish_build(build)
    catalog.stage_build(build, [metadata(ids[1])])
    assert catalog.finish_build(build) == 2
    assert set(catalog.select_page(source).ids) == set(ids)
    catalog.fail_build(build)
    assert catalog.select_page(source).total == 2


def test_duplicate_or_failed_build_never_serves_partial_metadata(source):
    build = catalog.begin_build(source, expected_count=2)
    id = str(uuid4())
    catalog.stage_build(build, [metadata(id)])
    with pytest.raises(catalog.Conflict):
        catalog.stage_build(build, [metadata(id)])
    catalog.fail_build(build)
    with pytest.raises(catalog.Unavailable, match="failed"):
        catalog.select_page(source)
    replacement = catalog.begin_build(source, expected_count=0)
    assert catalog.finish_build(replacement) == 0
    assert catalog.select_page(source).total == 0


def test_pending_mutations_prevent_bootstrap_and_abort_requires_quiescence(source):
    seed(source, 1)
    mutation = catalog.begin_mutation(source, str(UUID(int=1)), kind="delete")
    with pytest.raises(catalog.Conflict, match="pending"):
        catalog.begin_build(source, expected_count=0)
    catalog.acknowledge(mutation, None)
    catalog.finalize(mutation)
    build = catalog.begin_build(source, expected_count=0)
    with pytest.raises(ValueError, match="worker has stopped"):
        catalog.abort_build(source, quiescent=False)
    assert catalog.abort_build(source, quiescent=True)
    assert not catalog.abort_build(source, quiescent=True)
    with pytest.raises(catalog.Conflict, match="ownership changed"):
        catalog.finish_build(build)
    replacement = catalog.begin_build(source, expected_count=0)
    assert catalog.finish_build(replacement) == 0


@pytest.mark.parametrize("kind", ["upsert", "delete"])
def test_proved_no_write_clears_pending_without_corrupting_existing_projection(
    source, kind
):
    seed(source, 1)
    id = str(UUID(int=1))

    def absent():
        raise catalog.NoWritePerformed("Known absence before provider delete")

    with pytest.raises(catalog.NoWritePerformed):
        catalog.write_through(
            source,
            id,
            kind=kind,
            metadata=metadata(id) if kind == "upsert" else None,
            operation=absent,
        )
    assert catalog.pending(source) == []
    assert catalog.select_page(source).total == (0 if kind == "delete" else 1)


def test_generic_provider_key_error_remains_uncertain(source):
    seed(source, 1)
    id = str(UUID(int=1))

    def uncertain():
        raise KeyError("Provider response could not be interpreted")

    with pytest.raises(KeyError):
        catalog.write_through(
            source, id, kind="delete", metadata=None, operation=uncertain
        )
    assert len(catalog.pending(source)) == 1
    with pytest.raises(catalog.Unavailable, match="unresolved"):
        catalog.select_page(source)


def test_real_sql_finalization_failure_rolls_back_entry_but_keeps_acknowledgement(
    source, monkeypatch
):
    seed(source, 1)
    id = str(UUID(int=1))
    original = catalog._entry
    calls = []

    def fail_after_sql(cursor, *args):
        original(cursor, *args)
        cursor.execute("SELECT 1/0")

    monkeypatch.setattr(catalog, "_entry", fail_after_sql)
    with pytest.raises(catalog.Unavailable, match="22012"):
        catalog.write_through(
            source,
            id,
            kind="upsert",
            metadata=metadata(id),
            operation=lambda: calls.append("provider"),
        )
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT tags FROM memory_catalog_entries WHERE source_key=%s AND id=%s",
            (source.key, id),
        )
        assert cursor.fetchone()[0] == ["keep"]
    mutation = catalog.pending(source)[0]
    assert mutation.acknowledged and calls == ["provider"]
    monkeypatch.setattr(catalog, "_entry", original)
    catalog.finalize(mutation)
    assert catalog.select_page(source, tags=["critical"]).ids == [id]
    assert calls == ["provider"]


def test_acknowledged_mutation_cannot_be_canceled(source):
    seed(source, 1)
    id = str(UUID(int=1))
    mutation = catalog.begin_mutation(source, id, kind="upsert")
    catalog.acknowledge(mutation, metadata(id))
    with pytest.raises(catalog.Conflict, match="cannot be canceled"):
        catalog.cancel_unstarted(mutation)
    assert catalog.pending(source)[0].acknowledged
    catalog.finalize(mutation)


def test_explicit_known_id_drift_repair_can_claim_without_pending_marker(source):
    seed(source, 2)
    missing = str(UUID(int=1))
    before = catalog.select_page(source)
    repair = catalog.claim_repair(source, missing, quiescent=True)
    assert [mutation.id for mutation in catalog.pending(source)] == [missing]
    with pytest.raises(catalog.Unavailable, match="unresolved"):
        catalog.check_page(source, before.generation)
    catalog.acknowledge(repair, None)
    catalog.finalize(repair)
    assert catalog.select_page(source).total == 1
    restored = str(uuid4())
    repair = catalog.claim_repair(source, restored, quiescent=True)
    catalog.acknowledge(repair, metadata(restored))
    catalog.finalize(repair)
    assert catalog.select_page(source, tags=["critical"]).ids == [restored]
    assert catalog.select_page(source).total == 2
