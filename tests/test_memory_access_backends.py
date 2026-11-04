from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Condition, Event, Lock
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from services.db import get_connection
from services.memory.backends import lancedb_backend, pgvector_backend, pinecone_backend
from tests.test_pgvector_backend import FakeEmbeddings


CREATED = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
ACCESSED = CREATED + timedelta(days=1)


def metadata(id):
    return {"id": id, "repo": "access-tests", "tags": '["keep"]',
            "created_at": CREATED.isoformat(), "updated_at": CREATED.isoformat(),
            "last_accessed_at": CREATED}


@pytest.fixture(params=[pgvector_backend, lancedb_backend], ids=["pgvector", "lancedb"])
def native_store(request, monkeypatch, tmp_path):
    backend = request.param
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    monkeypatch.setattr(pgvector_backend, "_initialized", False)
    embeddings = FakeEmbeddings()
    store = backend.get_vectorstore(embeddings)
    id = str(uuid4())
    store.add_documents([Document(page_content="Python architecture", metadata=metadata(id))], ids=[id])
    yield backend, store, embeddings, id
    if backend is pgvector_backend:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM memories WHERE id=%s", (id,))


def untouched_storage(backend, id):
    if backend is pgvector_backend:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT content,embedding::text,created_at,updated_at,tags,repo FROM memories WHERE id=%s", (id,))
            return cursor.fetchone()
    row = backend._get_table().search().where(f"id='{id}'", prefilter=True).limit(1).to_list()[0]
    row["metadata"].pop("last_accessed_at")
    return row


def test_native_touch_preserves_vector_and_payload_and_cannot_regress_or_resurrect(native_store):
    backend, _, embeddings, id = native_store
    before = untouched_storage(backend, id)
    embeddings.fail_on = "Python"
    missing = str(uuid4())

    assert backend.touch_accessed([id, missing, id], ACCESSED) == {id: ACCESSED.isoformat()}
    assert untouched_storage(backend, id) == before
    assert backend.touch_accessed([id], CREATED) == {id: ACCESSED.isoformat()}
    assert backend.get_rows([missing, id.upper(), id]) == [backend.get_row(id)]
    assert backend.get_row(id)["metadata"]["last_accessed_at"] == ACCESSED.isoformat()

    backend.delete_row(id)
    assert backend.touch_accessed([id], ACCESSED) == {}
    assert backend.get_row(id) is None


def test_content_replacement_retains_a_newer_stored_access(native_store):
    backend, store, _, id = native_store
    backend.touch_accessed([id], ACCESSED)

    store.add_documents([Document(page_content="Weather replacement", metadata=metadata(id))], ids=[id])

    row = backend.get_row(id)
    assert row["text"] == "Weather replacement"
    assert row["metadata"]["created_at"] == CREATED.isoformat()
    assert row["metadata"]["last_accessed_at"] == ACCESSED.isoformat()


@pytest.mark.parametrize("backend", [pgvector_backend, lancedb_backend, pinecone_backend])
@pytest.mark.parametrize("ids,stamp", [(["not-a-uuid"], ACCESSED), ([str(uuid4()), None], ACCESSED),
                                       ([str(uuid4())], ACCESSED.replace(tzinfo=None)), ([str(uuid4())], "2026-01-01")])
def test_touch_validates_the_entire_request_before_storage(backend, ids, stamp, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid requests must not access storage")

    if backend is pgvector_backend:
        monkeypatch.setattr(backend, "init", forbidden)
    else:
        monkeypatch.setattr(backend, "_get_index" if backend is pinecone_backend else "_get_table", forbidden)
    with pytest.raises(ValueError):
        backend.touch_accessed(ids, stamp)


@pytest.mark.parametrize("shape", ["datetime", "string", "null", "missing"])
def test_lancedb_legacy_timestamp_shapes_preserve_other_struct_fields(tmp_path, monkeypatch, shape):
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    id = str(uuid4())
    original = {"created_at": CREATED.isoformat(), "updated_at": CREATED.isoformat(), "owner's key": "keep"}
    if shape != "missing":
        original["last_accessed_at"] = {"datetime": CREATED.replace(tzinfo=None),
            "string": "2026-01-01T07:00:00-05:00", "null": None}[shape]
    records = [{"id": id, "text": "Keep", "vector": [1., 0.], "metadata": original}]
    if shape == "null":
        records.append({"id": str(uuid4()), "text": "Other", "vector": [0., 1.],
            "metadata": original | {"last_accessed_at": CREATED.isoformat()}})
    table = lancedb_backend._db().create_table("memories", records)
    before = deepcopy(table.to_arrow().to_pylist()[0])

    if shape in {"null", "missing"}:
        assert lancedb_backend.get_row(id)["metadata"].get("last_accessed_at") is None
    assert lancedb_backend.touch_accessed([id], ACCESSED) == {id: ACCESSED.isoformat()}
    after = table.to_arrow().to_pylist()[0]
    assert after["vector"] == before["vector"]
    assert after["text"] == before["text"]
    for field in ("created_at", "updated_at", "owner's key"):
        assert after["metadata"][field] == before["metadata"][field]


def test_lancedb_null_only_access_schema_fails_without_rewriting_data(tmp_path, monkeypatch):
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    id = str(uuid4())
    table = lancedb_backend._db().create_table("memories", [{"id": id, "text": "Keep", "vector": [1., 0.],
        "metadata": {"last_accessed_at": None}}])
    before = table.to_arrow().to_pylist()
    with pytest.raises(ValueError, match="null-only schema"):
        lancedb_backend.touch_accessed([id], ACCESSED)
    assert table.to_arrow().to_pylist() == before


def test_lancedb_content_replacement_and_access_share_a_write_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    store = lancedb_backend.get_vectorstore(FakeEmbeddings())
    id = str(uuid4())
    document = Document(page_content="Python original", metadata=metadata(id))
    store.add_documents([document], ids=[id])
    entered, release, attempted = Event(), Event(), Event()
    parent_add = lancedb_backend.LanceDBVectorStore.add_documents

    def paused_add(self, documents, **kwargs):
        entered.set()
        assert release.wait(5)
        return parent_add(self, documents, **kwargs)

    def touch():
        attempted.set()
        return lancedb_backend.touch_accessed([id], ACCESSED)

    monkeypatch.setattr(lancedb_backend.LanceDBVectorStore, "add_documents", paused_add)
    with ThreadPoolExecutor(max_workers=2) as executor:
        replacement = executor.submit(store.add_documents, [document], ids=[id])
        try:
            assert entered.wait(5)
            access = executor.submit(touch)
            assert attempted.wait(5)
            assert not access.done()
        finally:
            release.set()
        assert replacement.result(timeout=5) == [id]
        assert access.result(timeout=5) == {id: ACCESSED.isoformat()}
    assert lancedb_backend.get_row(id)["metadata"]["last_accessed_at"] == ACCESSED.isoformat()


def test_lancedb_content_replacement_preserves_access_when_omitted(tmp_path, monkeypatch):
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    store = lancedb_backend.get_vectorstore(FakeEmbeddings())
    id = str(uuid4())
    store.add_documents([Document(page_content="Python original", metadata=metadata(id))], ids=[id])
    lancedb_backend.touch_accessed([id], ACCESSED)
    replacement = metadata(id)
    replacement.pop("last_accessed_at")

    store.add_documents([Document(page_content="Python replacement", metadata=replacement)], ids=[id])

    assert lancedb_backend.get_row(id)["metadata"]["last_accessed_at"] == ACCESSED.isoformat()


@pytest.mark.parametrize("backend", [lancedb_backend, pinecone_backend])
@pytest.mark.parametrize("bad_ids", ["invalid", "duplicate"])
def test_content_writes_validate_every_id_before_storage(backend, bad_ids, monkeypatch):
    id = str(uuid4())
    documents = [Document(page_content="Keep", metadata=metadata(id)) for _ in range(2)]
    ids = [id, "not-a-uuid" if bad_ids == "invalid" else id]

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid batches must not access storage")

    monkeypatch.setattr(backend, "_prepare_table" if backend is lancedb_backend else "_get_index", forbidden)
    cls = backend._UpsertingLanceDBVectorStore if backend is lancedb_backend else backend._SafePineconeVectorStore
    store = cls.__new__(cls)
    with pytest.raises(ValueError):
        store.add_documents(documents, ids=ids)


class PineconeRecords:
    def __init__(self, count=1):
        self.records = {}
        for _ in range(count):
            id = str(uuid4())
            self.records[id] = {"values": [1., 0.], "metadata": metadata(id) | {
                "text": "Keep Python", "last_accessed_at": CREATED.isoformat()}}
        self.fetches = []
        self.updates = []
        self.condition = Condition(Lock())
        self.active = 0
        self.maximum_active = 0
        self.release = None
        self.fail = False
        self.delete_during_update = False

    def fetch(self, ids, **kwargs):
        self.fetches.append((ids, kwargs))
        return {"vectors": {id: deepcopy(self.records[id]) for id in ids if id in self.records}}

    def update(self, *, id, set_metadata, **kwargs):
        with self.condition:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.condition.notify_all()
        try:
            if self.release is not None:
                assert self.release.wait(5)
            if self.fail:
                raise RuntimeError("Synthetic Pinecone update failure")
            self.updates.append((id, deepcopy(set_metadata), kwargs))
            if self.delete_during_update:
                self.records.pop(id, None)
            if id in self.records:
                self.records[id]["metadata"].update(set_metadata)
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


def test_pinecone_touch_only_patches_metadata_and_respects_missing_and_newer_values(monkeypatch):
    index = PineconeRecords(2)
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: index)
    first, newer = index.records
    index.records[newer]["metadata"]["last_accessed_at"] = (ACCESSED + timedelta(days=1)).isoformat()
    before = deepcopy(index.records)

    result = pinecone_backend.touch_accessed([first, newer, str(uuid4())], ACCESSED)

    assert result == {first: ACCESSED.isoformat(), newer: (ACCESSED + timedelta(days=1)).isoformat()}
    assert len(index.fetches) == 1
    assert len(index.updates) == 1
    assert index.updates[0][1] == {"last_accessed_at": ACCESSED.isoformat()}
    for _, kwargs in index.fetches:
        assert 0 < kwargs["_request_timeout"] <= 10
    for _, _, kwargs in index.updates:
        assert 0 < kwargs["_request_timeout"] <= 10
    for id, record in index.records.items():
        assert record["values"] == before[id]["values"]
        for field, value in before[id]["metadata"].items():
            if field != "last_accessed_at":
                assert record["metadata"][field] == value


def test_pinecone_parallelism_is_bounded_and_failures_release_the_batch_lock(monkeypatch):
    index = PineconeRecords(9)
    index.release = Event()
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: index)
    with ThreadPoolExecutor(max_workers=1) as caller:
        future = caller.submit(pinecone_backend.touch_accessed, list(index.records), ACCESSED)
        try:
            with index.condition:
                assert index.condition.wait_for(lambda: index.active == 4, timeout=5)
        finally:
            index.release.set()
        assert len(future.result(timeout=5)) == 9
    assert index.maximum_active == 4

    index.fail = True
    with pytest.raises(RuntimeError, match="Synthetic Pinecone update failure"):
        pinecone_backend.touch_accessed(list(index.records), ACCESSED + timedelta(days=1))
    index.fail = False
    assert len(pinecone_backend.touch_accessed(list(index.records), ACCESSED + timedelta(days=1))) == 9


def test_pinecone_touch_does_not_resurrect_deletion_between_fetch_and_patch(monkeypatch):
    index = PineconeRecords()
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: index)
    id = next(iter(index.records))
    index.delete_during_update = True

    assert pinecone_backend.touch_accessed([id], ACCESSED) == {id: ACCESSED.isoformat()}
    assert index.records == {}


@pytest.mark.parametrize("omit_access", [False, True])
def test_pinecone_content_write_preserves_newer_access_and_canonicalizes_utc(monkeypatch, omit_access):
    index = PineconeRecords()
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: index)
    id = next(iter(index.records))
    index.records[id]["metadata"]["last_accessed_at"] = ACCESSED.isoformat()
    captured = []

    def parent_add(self, documents, **kwargs):
        captured.extend(documents)
        return kwargs["ids"]

    monkeypatch.setattr(pinecone_backend.PineconeVectorStore, "add_documents", parent_add)
    incoming = metadata(id) | {"updated_at": "2026-01-02T07:00:00-05:00"}
    if omit_access:
        incoming.pop("last_accessed_at")
    original = Document(page_content="New content", metadata=incoming)
    store = pinecone_backend._SafePineconeVectorStore.__new__(pinecone_backend._SafePineconeVectorStore)
    assert store.add_documents([original], ids=[id]) == [id]
    assert captured[0].metadata["last_accessed_at"] == ACCESSED.isoformat()
    assert captured[0].metadata["updated_at"] == ACCESSED.isoformat()
    assert original.metadata.get("last_accessed_at") == (None if omit_access else CREATED)


def test_pinecone_deadline_prevents_issuing_updates_after_a_slow_fetch(monkeypatch):
    index = PineconeRecords()
    current = [0.]
    original_fetch = index.fetch

    def slow_fetch(ids, **kwargs):
        result = original_fetch(ids, **kwargs)
        current[0] = pinecone_backend.ACCESS_BATCH_SECONDS + 1
        return result

    monkeypatch.setattr(index, "fetch", slow_fetch)
    monkeypatch.setattr(pinecone_backend.time, "monotonic", lambda: current[0])
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: index)

    with pytest.raises(TimeoutError, match="deadline"):
        pinecone_backend.touch_accessed(list(index.records), ACCESSED)

    assert index.updates == []
