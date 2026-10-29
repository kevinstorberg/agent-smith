from concurrent.futures import ThreadPoolExecutor
from threading import Condition, Event, Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.memory import db
from services.memory.backends import lancedb_backend
from tests.test_pgvector_backend import FakeEmbeddings


class ObservedLock:
    def __init__(self):
        self._lock = Lock()
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


@pytest.fixture(autouse=True)
def isolated_memory(monkeypatch):
    monkeypatch.setattr(db, "_embeddings", None)
    monkeypatch.setattr(db, "_retriever", None)


@pytest.mark.parametrize("device", ["cpu", "mps", "cuda:1"])
def test_embedding_factory_constructs_once_and_forwards_device(monkeypatch, device):
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
    assert calls == [{"model_name": db.MODEL_NAME, "model_kwargs": {"device": device}}]
    assert results[0].embed_query("synthetic") == model.embed_query("synthetic")


def test_failed_embedding_initialization_can_retry_without_fallback(monkeypatch):
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
    assert [attempt["model_kwargs"] for attempt in attempts] == [{"device": "mps"}] * 2


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
    monkeypatch.setattr(db, "_id_based_salient_docs", lambda retriever, _: retriever)
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
    db._retriever = None
    assert retriever.get_salient_docs("query") is retriever


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
    monkeypatch.setattr(db, "TimeWeightedVectorStoreRetriever", lambda **kwargs: SimpleNamespace(**kwargs, memory_stream=[]))
    with pytest.raises(RuntimeError, match="Synthetic backend unavailable"):
        db._get_retriever()
    assert db._retriever is None
    assert db._get_retriever() is db._get_retriever()
    assert len(loads) == 2


def test_protected_embeddings_reach_publication_fresh_search_and_retriever(monkeypatch, tmp_path):
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
    retriever = db._get_retriever()
    assert retriever.invoke("Synthetic shared embedding")[0].metadata["id"] == id
    assert len(constructed) == 1
