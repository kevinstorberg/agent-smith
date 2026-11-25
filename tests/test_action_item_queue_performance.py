from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
from queue import Queue
from time import perf_counter

from psycopg2.extras import RealDictCursor
import pytest

from services.action_items import db, queue_db
from services.db import get_connection
from tests.jobs.test_scheduling_runtime import database_blocked_by
from tests.test_action_item_epics import current, epic, membership
from tests.test_action_items import action_items_empty as action_items_empty


@contextmanager
def measured_queries(monkeypatch):
    original = db.get_connection
    calls = []

    class TimedCursor(RealDictCursor):
        def execute(self, query, parameters=None):
            started = perf_counter()
            try:
                return super().execute(query, parameters)
            finally:
                calls.append(
                    {
                        "sql": " ".join(str(query).split()),
                        "milliseconds": (perf_counter() - started) * 1000,
                    }
                )

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        def cursor(self, **kwargs):
            return self.connection.cursor(cursor_factory=TimedCursor)

    @contextmanager
    def connection():
        with original() as native:
            yield Connection(native)

    with monkeypatch.context() as patch:
        patch.setattr(db, "get_connection", connection)
        yield calls


def report(label, calls, milliseconds):
    result = {
        "operation": label,
        "execute_count": len(calls),
        "total_ms": milliseconds,
        "statement_ms": sum(call["milliseconds"] for call in calls),
        "uncontended_lock_statement_ms": sum(
            call["milliseconds"]
            for call in calls
            if "pg_advisory_xact_lock" in call["sql"]
        ),
        "queries": calls,
    }
    print("ACTION_ITEM_QUERY_MEASUREMENT " + json.dumps(result))


def test_membership_query_budget(monkeypatch, action_items_empty):
    first = db.create({"title": "Visible source", "project": "Work"})
    parent = epic("Source", item=first)
    first = db.get(first["id"])
    sibling = db.create({"title": "Visible destination", "project": "Work"})
    destination = epic("Destination", item=sibling)
    parent, destination = current(parent["id"]), current(destination["id"])

    with measured_queries(monkeypatch) as calls:
        started = perf_counter()
        moved = membership(first, parent=parent, destination=destination)
        milliseconds = (perf_counter() - started) * 1000
    report("open_epic_to_epic", calls, milliseconds)
    assert len(calls) == 14
    assert moved["revision"] == first["revision"] + 1
    assert moved["priority"] is not None

    with measured_queries(monkeypatch) as calls:
        started = perf_counter()
        queue = queue_db.list_queue({"q": "Visible", "project": "Work"})
        milliseconds = (perf_counter() - started) * 1000
    report("filtered_queue_read", calls, milliseconds)
    assert len(calls) == 5
    children = [child for root in queue["items"] for child in root["children"]]
    assert {child["item"]["id"] for child in children} == {
        first["id"],
        sibling["id"],
    }


@pytest.mark.parametrize("write", [False, True])
@pytest.mark.parametrize("rollback", [False, True])
def test_batched_transaction_settings_remain_local(monkeypatch, write, rollback):
    with get_connection() as connection:

        def settings():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT current_setting('TimeZone'),current_setting('lock_timeout'),"
                    "current_setting('statement_timeout'),current_setting('transaction_isolation')"
                )
                return cursor.fetchone()

        original = settings()
        connection.commit()

        @contextmanager
        def borrowed():
            with connection:
                yield connection

        monkeypatch.setattr(db, "get_connection", borrowed)

        def transaction():
            with db._cursor(None, write=write):
                assert settings() == (
                    "UTC",
                    "5s",
                    "5s",
                    original[3] if write else "repeatable read",
                )
                if rollback:
                    raise RuntimeError("Intentional transaction rollback")

        if rollback:
            with pytest.raises(RuntimeError, match="Intentional"):
                transaction()
        else:
            transaction()
        assert settings() == original


def test_batched_lock_uses_six_second_statement_timeout(monkeypatch):
    monkeypatch.setattr(
        db,
        "_WRITE_LOCK_SQL",
        db._WRITE_LOCK_SQL + "; SELECT set_config('agent_smith.observed_lock_timeout',"
        "current_setting('statement_timeout'),true)",
    )
    with db._cursor(None, write=True) as (cursor, _):
        cursor.execute(
            "SELECT current_setting('agent_smith.observed_lock_timeout') AS during_lock,"
            "current_setting('statement_timeout') AS after_lock"
        )
        assert dict(cursor.fetchone()) == {"during_lock": "6s", "after_lock": "5s"}


def test_batched_read_keeps_its_repeatable_snapshot():
    task = db.create({"title": "Before"})
    with db._cursor(None, write=False) as (cursor, _):
        cursor.execute("SELECT title FROM action_items WHERE id=%s", (task["id"],))
        assert cursor.fetchone()["title"] == "Before"
        db.update(task["id"], {"title": "After", "expected_revision": task["revision"]})
        cursor.execute("SELECT title FROM action_items WHERE id=%s", (task["id"],))
        assert cursor.fetchone()["title"] == "Before"
    assert db.get(task["id"])["title"] == "After"


def test_batched_write_still_waits_for_the_authoritative_lock(monkeypatch):
    connected = Queue()
    original = db.get_connection

    @contextmanager
    def recorded():
        with original() as connection:
            connected.put(connection.get_backend_pid())
            yield connection

    def transaction():
        started = perf_counter()
        with db._cursor(None, write=True) as (cursor, _):
            cursor.execute("SELECT current_setting('statement_timeout') AS timeout")
            assert cursor.fetchone()["timeout"] == "5s"
        return (perf_counter() - started) * 1000

    with get_connection() as blocker, blocker.cursor() as cursor:
        db.acquire_write_lock(cursor)
        monkeypatch.setattr(db, "get_connection", recorded)
        with ThreadPoolExecutor(max_workers=1) as executor:
            waiting = executor.submit(transaction)
            database_blocked_by(connected.get(timeout=2), blocker.get_backend_pid())
            assert not waiting.done()
            blocker.commit()
            print("ACTION_ITEM_CONTENDED_LOCK_TOTAL_MS", waiting.result(timeout=7))
