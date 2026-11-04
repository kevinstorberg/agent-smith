from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from services.db import get_connection
from services.memory import db
from services.memory.backends import get_backend, lancedb_backend, pgvector_backend
from tests.test_pgvector_backend import FakeEmbeddings


CREATED = datetime(2026, 11, 4, 14, 15, 16, tzinfo=timezone.utc)
ACCESSED = CREATED + timedelta(hours=1)


@pytest.fixture(autouse=True)
def non_utc_timezone(monkeypatch):
    previous = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    if previous is None:
        monkeypatch.delenv("TZ")
    else:
        monkeypatch.setenv("TZ", previous)
    time.tzset()


@pytest.fixture(params=["pgvector", "lancedb"])
def memory_backend(request, monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_BACKEND", request.param)
    monkeypatch.setattr(db, "_embeddings", FakeEmbeddings())
    monkeypatch.setattr(db, "_retriever", None)
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    monkeypatch.setattr(pgvector_backend, "_initialized", False)
    if request.param == "pgvector":
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM memories")
    yield get_backend()
    db._retriever = None
    if request.param == "pgvector":
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM memories")


@pytest.fixture
def clock(monkeypatch):
    current = [CREATED]
    monkeypatch.setattr(db, "_utcnow", lambda: current[0])
    return current


@pytest.fixture
def memory_client():
    from services.api.routers import memory

    app = FastAPI()
    app.include_router(memory.router, prefix="/memory")
    with TestClient(app) as client:
        yield client


def instant(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
    return parsed


def stored_access(backend, memory_id):
    return instant(backend.get_row(memory_id)["metadata"]["last_accessed_at"])


def assert_untouched_fields(before, after):
    assert after["text"] == before["text"]
    for field in ("created_at", "updated_at", "repo", "tags"):
        assert after["metadata"][field] == before["metadata"][field]
    if "vector" in before:
        assert after["vector"] == before["vector"]


def test_memory_write_timestamps_remain_utc_on_non_utc_host(memory_backend, clock):
    memory_id = db.add("Python architecture", repo="project", tags=["keep"])
    initial = memory_backend.get_row(memory_id)
    assert {
        instant(initial["metadata"][field])
        for field in ("created_at", "updated_at", "last_accessed_at")
    } == {CREATED}

    clock[0] = ACCESSED
    db.update(memory_id, content="Updated architecture")
    updated = db.get(memory_id, record_access=False)
    assert instant(updated["created_at"]) == CREATED
    assert instant(updated["updated_at"]) == ACCESSED
    instant(updated["last_accessed_at"])

    published_id = str(uuid4())
    db.publish(published_id, "Published summary fact", created_at="2026-07-12T16:15:16+02:00")
    published = db.get(published_id, record_access=False)
    assert published["created_at"] == "2026-07-12T14:15:16+00:00"
    for field in ("created_at", "updated_at", "last_accessed_at"):
        instant(published[field])


def test_get_records_real_access_and_list_only_observes_it(memory_backend, clock):
    memory_id = db.add("Python architecture")
    before = deepcopy(memory_backend.get_row(memory_id))
    clock[0] = ACCESSED

    assert instant(db.get(memory_id, record_access=False)["last_accessed_at"]) == CREATED
    assert stored_access(memory_backend, memory_id) == CREATED
    assert instant(db.get(memory_id)["last_accessed_at"]) == ACCESSED
    assert stored_access(memory_backend, memory_id) == ACCESSED
    assert_untouched_fields(before, memory_backend.get_row(memory_id))

    clock[0] += timedelta(hours=1)
    assert instant(db.list_memories()[0]["last_accessed_at"]) == ACCESSED
    db._retriever = None
    assert instant(db.list_memories()[0]["last_accessed_at"]) == ACCESSED
    assert stored_access(memory_backend, memory_id) == ACCESSED


def test_fresh_search_persists_access_without_loading_cached_stream(memory_backend, clock, monkeypatch):
    memory_id = str(uuid4())
    db.publish(memory_id, "Python architecture", created_at=CREATED.isoformat())
    before = deepcopy(memory_backend.get_row(memory_id))
    clock[0] = ACCESSED

    def forbidden_load(*args, **kwargs):
        raise AssertionError("Fresh search must not hydrate the cached memory stream")

    monkeypatch.setattr(db, "_get_retriever", forbidden_load)
    monkeypatch.setattr(memory_backend, "load_all", forbidden_load)
    result = db.search_fresh("Python architecture", limit=1)

    assert [row["id"] for row in result] == [memory_id]
    assert instant(result[0]["last_accessed_at"]) == ACCESSED
    assert stored_access(memory_backend, memory_id) == ACCESSED
    assert db._retriever is None
    assert_untouched_fields(before, memory_backend.get_row(memory_id))


@pytest.mark.parametrize("operation", ["get", "search_fresh", "search"])
def test_failed_access_write_does_not_mutate_cached_or_stored_memory(memory_backend, clock, monkeypatch, operation):
    memory_id = db.add("Python architecture")
    before_cache = deepcopy(db._get_retriever().memory_stream)
    before_row = deepcopy(memory_backend.get_row(memory_id))
    clock[0] = ACCESSED

    def failed_touch(*args, **kwargs):
        raise RuntimeError("Synthetic access persistence failure")

    monkeypatch.setattr(memory_backend, "touch_accessed", failed_touch)
    with pytest.raises(RuntimeError, match="Synthetic access persistence failure"):
        if operation == "get":
            db.get(memory_id)
        elif operation == "search_fresh":
            db.search_fresh("Python architecture", limit=1)
        else:
            db.search("Python architecture", limit=1)

    assert db._get_retriever().memory_stream == before_cache
    assert memory_backend.get_row(memory_id) == before_row


def test_standard_search_persists_access_after_cache_reload(memory_backend, clock):
    memory_id = db.add("Python architecture", repo="project", tags=["keep"])
    before = deepcopy(memory_backend.get_row(memory_id))
    clock[0] = ACCESSED

    result = db.search("Python architecture", limit=1)
    assert [row["id"] for row in result] == [memory_id]
    assert instant(result[0]["last_accessed_at"]) == ACCESSED
    assert stored_access(memory_backend, memory_id) == ACCESSED
    assert_untouched_fields(before, memory_backend.get_row(memory_id))

    db._retriever = None
    assert instant(db.list_memories()[0]["last_accessed_at"]) == ACCESSED


@pytest.mark.parametrize("offset", [1, 99])
def test_http_search_only_touches_returned_filtered_page(memory_backend, clock, memory_client, offset):
    matching = []
    originals = {}
    for index in range(3):
        clock[0] = CREATED + timedelta(seconds=index)
        memory_id = db.add("Python architecture", repo="project", tags=["keep"])
        matching.append(memory_id)
        originals[memory_id] = clock[0]
    for repo, tags in [("other", ["keep"]), ("project", ["drop"])]:
        memory_id = db.add("Python architecture", repo=repo, tags=tags)
        originals[memory_id] = clock[0]
    clock[0] = ACCESSED
    response = memory_client.get("/memory/search", params={
        "q": "Python architecture", "repo": "project", "tags": "keep",
        "sort": "created_at_asc", "offset": offset, "limit": 1,
    })

    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 3
    expected = [matching[1]] if offset == 1 else []
    assert [row["id"] for row in page["items"]] == expected
    for memory_id, original in originals.items():
        assert stored_access(memory_backend, memory_id) == (ACCESSED if memory_id in expected else original)


def test_http_update_does_not_record_internal_response_reads(memory_backend, clock, memory_client, monkeypatch):
    memory_id = db.add("Original Python architecture")
    clock[0] = ACCESSED

    def forbidden_touch(*args, **kwargs):
        raise AssertionError("Maintenance reads must not record memory access")

    monkeypatch.setattr(memory_backend, "touch_accessed", forbidden_touch)
    response = memory_client.put(f"/memory/{memory_id}", json={"content": "Corrected Python architecture"})

    assert response.status_code == 200
    updated = response.json()
    assert updated["content"] == "Corrected Python architecture"
    assert instant(updated["created_at"]) == CREATED
    assert instant(updated["updated_at"]) == ACCESSED
    assert memory_backend.get_row(memory_id)["text"] == updated["content"]


def test_list_page_refreshes_stored_access_without_touching_it(memory_backend, clock):
    db.add("First Python memory")
    clock[0] += timedelta(seconds=1)
    selected_id = db.add("Second Python memory")
    memory_backend.touch_accessed([selected_id], ACCESSED)
    clock[0] = ACCESSED + timedelta(hours=1)

    result, total = db.list_page(sort="created_at_asc", offset=1, limit=1)

    assert total == 2
    assert [row["id"] for row in result] == [selected_id]
    assert instant(result[0]["last_accessed_at"]) == ACCESSED
    assert stored_access(memory_backend, selected_id) == ACCESSED


def test_ranking_uses_current_stored_access_instead_of_stale_cache(memory_backend, clock):
    selected_id = db.add("Python architecture")
    clock[0] += timedelta(seconds=1)
    db.add("Python architecture")
    cached = next(doc for doc in db._get_retriever().memory_stream if doc.metadata["id"] == selected_id)
    memory_backend.touch_accessed([selected_id], ACCESSED)
    assert instant(cached.metadata["last_accessed_at"]) == CREATED
    clock[0] = ACCESSED + timedelta(hours=1)

    assert db.search("Python architecture", limit=1)[0]["id"] == selected_id


@pytest.mark.parametrize("cached_memory", [False, True])
def test_search_includes_external_vector_hit_missing_from_warm_cache(memory_backend, clock, cached_memory):
    if cached_memory:
        db.add("Python architecture")
    else:
        db._get_retriever()
    external_id = str(uuid4())
    external = Document(page_content="Weather report", metadata={
        "id": external_id, "repo": "", "tags": "[]",
        "created_at": ACCESSED.isoformat(), "updated_at": ACCESSED.isoformat(),
        "last_accessed_at": ACCESSED,
        "source_type": "general", "source_id": external_id,
    })
    memory_backend.get_vectorstore(db._get_embeddings()).add_documents([external], ids=[external_id])
    clock[0] = ACCESSED + timedelta(hours=1)

    result = db.search("Weather report", limit=1)

    assert [row["id"] for row in result] == [external_id]
    assert stored_access(memory_backend, external_id) == clock[0]


def test_legacy_cached_metadata_uses_authoritative_outer_id(memory_backend, clock, monkeypatch):
    memory_id = db.add("Python architecture")
    original_load = memory_backend.load_all

    def legacy_rows():
        rows = deepcopy(original_load())
        for row in rows:
            row["metadata"].pop("id", None)
        return rows

    db._retriever = None
    monkeypatch.setattr(memory_backend, "load_all", legacy_rows)
    assert db.get(memory_id, record_access=False)["id"] == memory_id
    assert [row["id"] for row in db.list_memories()] == [memory_id]
    clock[0] = ACCESSED

    assert db.search("Python architecture", limit=1)[0]["id"] == memory_id
    assert stored_access(memory_backend, memory_id) == ACCESSED


def test_access_does_not_overwrite_a_concurrent_content_update(memory_backend, clock, monkeypatch):
    memory_id = db.add("Old Python architecture", tags=["old"])
    original_touch = memory_backend.touch_accessed
    metadata = deepcopy(memory_backend.get_row(memory_id)["metadata"])
    metadata.update(updated_at=ACCESSED.isoformat(), tags='["corrected"]')
    clock[0] = ACCESSED + timedelta(hours=1)

    def concurrent_correction(ids, accessed_at):
        document = Document(page_content="Human-corrected Python architecture", metadata=metadata)
        memory_backend.get_vectorstore(db._get_embeddings()).add_documents([document], ids=[memory_id])
        return original_touch(ids, accessed_at)

    monkeypatch.setattr(memory_backend, "touch_accessed", concurrent_correction)
    assert db.search("Python architecture", limit=1)[0]["id"] == memory_id

    saved = db.get(memory_id, record_access=False)
    assert saved["content"] == "Human-corrected Python architecture"
    assert saved["tags"] == ["corrected"]
    assert instant(saved["updated_at"]) == ACCESSED
    assert instant(saved["last_accessed_at"]) == clock[0]


def test_subprocess_access_is_visible_to_warm_feed_and_after_reload(memory_backend, clock):
    memory_id = db.add("Python architecture")
    environment = dict(os.environ)
    environment["MEMORY_STORE_PATH"] = str(lancedb_backend.STORE_PATH)
    program = """
from datetime import datetime
import json
import sys
from scripts.shared.automated_tests import activate_automated_tests
activate_automated_tests()
from services.memory import db
db._utcnow = lambda: datetime.fromisoformat(sys.argv[2])
row = db.get(sys.argv[1])
print(json.dumps({"id": row["id"], "last_accessed_at": row["last_accessed_at"]}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", program, memory_id, ACCESSED.isoformat()],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        check=True, capture_output=True, text=True, timeout=30,
    )
    assert json.loads(completed.stdout) == {"id": memory_id, "last_accessed_at": ACCESSED.isoformat()}

    clock[0] = ACCESSED + timedelta(hours=1)
    assert instant(db.list_memories()[0]["last_accessed_at"]) == ACCESSED
    db._retriever = None
    assert instant(db.list_memories()[0]["last_accessed_at"]) == ACCESSED
    assert stored_access(memory_backend, memory_id) == ACCESSED
