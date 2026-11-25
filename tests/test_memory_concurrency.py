from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta
from threading import Barrier, Condition, Event, RLock
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.memory import db
from services.memory.backends import lancedb_backend
from tests.test_pgvector_backend import FakeEmbeddings


class ObservedLock:
    def __init__(self):
        self._lock = RLock()
        self._condition = Condition()
        self._attempts = 0

    def __enter__(self):
        with self._condition:
            self._attempts += 1
            self._condition.notify_all()
        self._lock.acquire()
        return self

    def __exit__(self, *_):
        self._lock.release()

    def wait_for_attempts(self, count):
        with self._condition:
            assert self._condition.wait_for(lambda: self._attempts >= count, timeout=5)

    @property
    def attempts(self):
        with self._condition:
            return self._attempts


@pytest.fixture(autouse=True)
def isolated_memory(monkeypatch):
    monkeypatch.setattr(db, "_embeddings", None)
    monkeypatch.setattr(db, "_retriever", None)


@pytest.fixture
def synthetic_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_BACKEND", "lancedb")
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    monkeypatch.setattr(db, "_embeddings", FakeEmbeddings())
    store = lancedb_backend.get_vectorstore(db._embeddings)
    monkeypatch.setattr(lancedb_backend, "get_vectorstore", lambda _: store)
    return SimpleNamespace(backend=lancedb_backend, store=store)


@pytest.fixture
def paused_catalog(synthetic_memory, monkeypatch):
    catalog = synthetic_memory
    catalog.loading, catalog.release = Event(), Event()
    catalog.lock, catalog.loads = ObservedLock(), []
    catalog.failure = None
    catalog.read_rows = catalog.backend.load_all

    def load_all():
        rows = catalog.read_rows()
        catalog.loads.append(len(rows))
        catalog.loading.set()
        assert catalog.release.wait(5)
        if catalog.failure is not None:
            raise catalog.failure
        return rows

    monkeypatch.setattr(catalog.backend, "load_all", load_all)
    monkeypatch.setattr(db, "_retriever_lock", catalog.lock)
    yield catalog
    catalog.release.set()


@pytest.mark.parametrize("operation", ["add", "update", "delete"])
def test_acknowledged_write_reconciles_after_listing_snapshot(
    paused_catalog, monkeypatch, operation
):
    catalog = paused_catalog
    existing_id = db.add("Original Python memory")
    mutated = Event()
    original_write = catalog.store.add_documents
    original_delete = catalog.backend.delete_row

    def write(*args, **kwargs):
        result = original_write(*args, **kwargs)
        mutated.set()
        return result

    def delete(id):
        original_delete(id)
        mutated.set()

    def change():
        if operation == "add":
            return db.add("Another Python memory")
        if operation == "update":
            return db.update(existing_id, content="Corrected Python memory")
        return db.delete(existing_id)

    monkeypatch.setattr(catalog.store, "add_documents", write)
    monkeypatch.setattr(catalog.backend, "delete_row", delete)
    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            listing = pool.submit(db._get_retriever)
            assert catalog.loading.wait(5)
            next_attempt = catalog.lock.attempts + 1
            writer = pool.submit(change)
            assert mutated.wait(5)
            catalog.lock.wait_for_attempts(next_attempt)
            assert db._retriever is None and not writer.done()
        finally:
            catalog.release.set()
        retriever = listing.result(timeout=5)
        writer.result(timeout=5)

    stored = {row["id"]: row["text"] for row in catalog.read_rows()}
    cached = {doc.metadata["id"]: doc.page_content for doc in retriever.memory_stream}
    assert cached == stored
    assert [doc.metadata["buffer_idx"] for doc in retriever.memory_stream] == list(
        range(len(stored))
    )
    assert {row["id"]: row["content"] for row in db.list_memories()} == stored
    assert catalog.loads == [1]


@pytest.mark.parametrize("operation", ["add", "update"])
def test_failed_write_during_listing_leaves_snapshot_and_storage_unchanged(
    paused_catalog, monkeypatch, operation
):
    catalog = paused_catalog
    id = db.add("Keep this Python memory")
    before = deepcopy(catalog.read_rows())

    def failed_write(*args, **kwargs):
        raise RuntimeError("Synthetic storage write failure")

    monkeypatch.setattr(catalog.store, "add_documents", failed_write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            listing = pool.submit(db._get_retriever)
            assert catalog.loading.wait(5)
            writer = pool.submit(
                db.add if operation == "add" else db.update,
                *(["Uncommitted Python memory"] if operation == "add" else [id]),
                **(
                    {}
                    if operation == "add"
                    else {"content": "Uncommitted Python memory"}
                ),
            )
            with pytest.raises(RuntimeError, match="Synthetic storage write failure"):
                writer.result(timeout=5)
            assert db._retriever is None
        finally:
            catalog.release.set()
        retriever = listing.result(timeout=5)

    assert catalog.read_rows() == before
    assert [
        (doc.metadata["id"], doc.page_content) for doc in retriever.memory_stream
    ] == [(id, "Keep this Python memory")]


def test_successful_write_survives_failed_listing_and_next_initialization(
    paused_catalog, monkeypatch
):
    catalog = paused_catalog
    existing_id = db.add("Existing Python memory")
    catalog.failure = RuntimeError("Synthetic listing failure")
    persisted = Event()
    original_write = catalog.store.add_documents

    def write(*args, **kwargs):
        result = original_write(*args, **kwargs)
        persisted.set()
        return result

    monkeypatch.setattr(catalog.store, "add_documents", write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            listing = pool.submit(db._get_retriever)
            assert catalog.loading.wait(5)
            next_attempt = catalog.lock.attempts + 1
            writer = pool.submit(db.add, "Acknowledged Python memory")
            assert persisted.wait(5)
            catalog.lock.wait_for_attempts(next_attempt)
            assert db._retriever is None and not writer.done()
        finally:
            catalog.release.set()
        with pytest.raises(RuntimeError, match="Synthetic listing failure"):
            listing.result(timeout=5)
        written_id = writer.result(timeout=5)

    assert db._retriever is None
    catalog.failure = None
    rows, total = db.list_page(limit=10)
    assert total == 2 and {row["id"] for row in rows} == {existing_id, written_id}
    assert catalog.loads == [1, 2]


def test_search_completes_during_listing_and_page_refreshes_acknowledged_access(
    paused_catalog, monkeypatch
):
    catalog = paused_catalog
    id = db.add("Python memory")
    initial = catalog.backend.get_row(id)["metadata"]["last_accessed_at"]
    accessed = datetime.fromisoformat(initial) if isinstance(initial, str) else initial
    accessed += timedelta(hours=1)
    monkeypatch.setattr(db, "_utcnow", lambda: accessed)

    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            listing = pool.submit(db._get_retriever)
            assert catalog.loading.wait(5)
            result = pool.submit(db.search, "Python memory", limit=1).result(timeout=5)
            assert [row["id"] for row in result] == [id]
            assert datetime.fromisoformat(result[0]["last_accessed_at"]) == accessed
            assert db._retriever is None and not listing.done()
        finally:
            catalog.release.set()
        listing.result(timeout=5)

    assert datetime.fromisoformat(db.list_memories()[0]["last_accessed_at"]) == accessed
    assert catalog.loads == [1]


def test_concurrent_writes_resolve_distinct_in_memory_indexes(
    synthetic_memory, monkeypatch
):
    retriever = db._get_retriever()
    written = Barrier(2)
    original_write = synthetic_memory.store.add_documents

    def write(*args, **kwargs):
        result = original_write(*args, **kwargs)
        written.wait(timeout=5)
        return result

    monkeypatch.setattr(synthetic_memory.store, "add_documents", write)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(db.add, ["First Python memory", "Second Python memory"]))

    assert {doc.metadata["id"] for doc in retriever.memory_stream} == set(ids)
    assert [doc.metadata["buffer_idx"] for doc in retriever.memory_stream] == [0, 1]


@pytest.mark.parametrize("device", ["cpu", "mps", "cuda:1"])
@pytest.mark.parametrize("offline", [False, True])
def test_embedding_factory_constructs_once_and_forwards_device(
    monkeypatch, device, offline
):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1" if offline else "0")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    entered, release = Event(), Event()
    lock = ObservedLock()
    calls = []
    model = FakeEmbeddings()

    def build(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(5)
        return model

    monkeypatch.setattr(db, "HuggingFaceEmbeddings", build)
    monkeypatch.setattr(db, "MEMORY_EMBEDDING_DEVICE", device)
    monkeypatch.setattr(db, "_embeddings_lock", lock)
    with ThreadPoolExecutor(max_workers=3) as pool:
        try:
            futures = [pool.submit(db._get_embeddings) for _ in range(3)]
            assert entered.wait(5)
            lock.wait_for_attempts(3)
            assert db._embeddings is None
            assert not any(future.done() for future in futures)
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]
    assert all(result is results[0] for result in results)
    model_kwargs = {"device": device}
    if offline:
        model_kwargs["local_files_only"] = True
    assert calls == [{"model_name": db.MODEL_NAME, "model_kwargs": model_kwargs}]
    assert results[0].embed_query("synthetic") == model.embed_query("synthetic")


@pytest.mark.parametrize("offline", [False, True])
def test_failed_embedding_initialization_can_retry_without_fallback(
    monkeypatch, offline
):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1" if offline else "0")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    attempts = []

    def build(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("Device unavailable")
        return FakeEmbeddings()

    monkeypatch.setattr(db, "HuggingFaceEmbeddings", build)
    monkeypatch.setattr(db, "MEMORY_EMBEDDING_DEVICE", "mps")
    with pytest.raises(RuntimeError, match="Device unavailable"):
        db._get_embeddings()
    assert db._embeddings is None
    assert db._get_embeddings() is db._get_embeddings()
    model_kwargs = {"device": "mps"}
    if offline:
        model_kwargs["local_files_only"] = True
    assert [attempt["model_kwargs"] for attempt in attempts] == [model_kwargs] * 2


def test_query_and_document_encodes_share_one_lock_and_recover_after_error():
    entered, release = Event(), Event()
    calls = []

    class Model(FakeEmbeddings):
        def embed_query(self, text):
            calls.append(("query", text))
            entered.set()
            assert release.wait(5)
            raise RuntimeError("Synthetic encoding failure")

        def embed_documents(self, texts):
            calls.append(("documents", texts))
            return [[1.0] for _ in texts]

    embeddings = db._SerializedEmbeddings(Model())
    lock = embeddings._lock = ObservedLock()
    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            query = pool.submit(embeddings.embed_query, "query")
            assert entered.wait(5)
            documents = pool.submit(embeddings.embed_documents, ["document"])
            lock.wait_for_attempts(2)
            assert calls == [("query", "query")]
            assert not documents.done()
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="Synthetic encoding failure"):
            query.result(timeout=5)
        assert documents.result(timeout=5) == [[1.0]]
    assert calls == [("query", "query"), ("documents", ["document"])]


def test_retriever_is_published_only_after_single_complete_hydration(monkeypatch):
    entered, release = Event(), Event()
    lock = ObservedLock()
    loads = []
    constructed = []

    def load_all():
        loads.append(True)
        entered.set()
        assert release.wait(5)
        return [{"text": "synthetic memory", "metadata": {"id": "one"}}]

    def build(**kwargs):
        retriever = SimpleNamespace(**kwargs, memory_stream=[])
        constructed.append(retriever)
        return retriever

    backend = SimpleNamespace(get_vectorstore=lambda _: object(), load_all=load_all)
    monkeypatch.setattr(db, "_embeddings", FakeEmbeddings())
    monkeypatch.setattr(db, "_retriever_lock", lock)
    monkeypatch.setattr(db, "get_backend", lambda: backend)
    monkeypatch.setattr(db, "TimeWeightedVectorStoreRetriever", build)
    with ThreadPoolExecutor(max_workers=3) as pool:
        try:
            futures = [pool.submit(db._get_retriever) for _ in range(3)]
            assert entered.wait(5)
            lock.wait_for_attempts(3)
            assert db._retriever is None
            assert not any(future.done() for future in futures)
        finally:
            release.set()
        retrievers = [future.result(timeout=5) for future in futures]
    assert len(loads) == len(constructed) == 1
    assert all(retriever is retrievers[0] for retriever in retrievers)
    retriever = retrievers[0]
    assert retriever.memory_stream[0].page_content == "synthetic memory"
    assert retriever.memory_stream[0].metadata["buffer_idx"] == 0


def test_failed_retriever_hydration_is_not_cached(monkeypatch):
    loads = []

    def load_all():
        loads.append(True)
        if len(loads) == 1:
            raise RuntimeError("Synthetic backend unavailable")
        return []

    backend = SimpleNamespace(get_vectorstore=lambda _: object(), load_all=load_all)
    monkeypatch.setattr(db, "_embeddings", FakeEmbeddings())
    monkeypatch.setattr(db, "get_backend", lambda: backend)
    monkeypatch.setattr(
        db,
        "TimeWeightedVectorStoreRetriever",
        lambda **kwargs: SimpleNamespace(**kwargs, memory_stream=[]),
    )
    with pytest.raises(RuntimeError, match="Synthetic backend unavailable"):
        db._get_retriever()
    assert db._retriever is None
    assert db._get_retriever() is db._get_retriever()
    assert len(loads) == 2


def test_protected_embeddings_reach_publication_fresh_search_and_retriever(
    monkeypatch, tmp_path
):
    calls = []

    class Model(FakeEmbeddings):
        def embed_documents(self, texts):
            calls.append("documents")
            return super().embed_documents(texts)

        def embed_query(self, text):
            calls.append("query")
            return super().embed_query(text)

    constructed = []

    def build(**kwargs):
        constructed.append(kwargs)
        return Model()

    monkeypatch.setenv("MEMORY_BACKEND", "lancedb")
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    monkeypatch.setattr(db, "HuggingFaceEmbeddings", build)
    id = str(uuid4())
    db.publish(id, "Synthetic shared embedding", created_at="2026-01-27T15:30:00+00:00")
    assert calls == ["documents"]
    assert db._retriever is None
    assert db.search_fresh("Synthetic shared embedding")[0]["id"] == id
    assert "query" in calls
    assert db.search("Synthetic shared embedding", limit=1)[0]["id"] == id
    assert len(constructed) == 1
