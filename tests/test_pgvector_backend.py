from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

import services.memory.backends.pgvector_backend as pgvector_backend
import services.memory.db as memory_db
from services.db import get_connection
from services.memory.backends import get_backend
from tests.shared_backend_contract import (
    VALID_ID,
    assert_delete_raises_if_missing,
    assert_get_row_not_found,
    assert_invalid_id_rejected,
)


def _embedding(x: float, y: float = 0.0) -> list[float]:
    return [x, y, *([0.0] * 382)]


class FakeEmbeddings(Embeddings):
    def __init__(self, *, fail_on: str | None = None, dimension: int = 384):
        self.fail_on = fail_on
        self.dimension = dimension

    def _embed(self, text: str) -> list[float]:
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("synthetic embedding failure")
        if self.dimension != 384:
            return [1.0] * self.dimension
        if "weather" in text.lower():
            return _embedding(0.0, 1.0)
        return _embedding(1.0)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _metadata(id: str, *, repo: str = "repo", tags: list[str] | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": id,
        "repo": repo,
        "tags": tags or [],
        "created_at": now,
        "updated_at": now,
        "last_accessed_at": now,
    }


@pytest.fixture(autouse=True)
def clean_memories(monkeypatch):
    monkeypatch.setenv("MEMORY_BACKEND", "pgvector")
    pgvector_backend._initialized = False
    memory_db._retriever = None
    memory_db._embeddings = FakeEmbeddings()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM memories")
    yield
    memory_db._retriever = None
    memory_db._embeddings = None
    pgvector_backend._initialized = False
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM memories")


def test_init_validates_and_registers_pgvector():
    pgvector_backend.init()
    assert pgvector_backend._initialized is True
    assert get_backend() is pgvector_backend


def test_init_rejects_rows_from_a_different_embedding_model():
    store = pgvector_backend.get_vectorstore(FakeEmbeddings())
    store.add_documents(
        [Document(page_content="Python code", metadata=_metadata(VALID_ID))],
        ids=[VALID_ID],
    )
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE memories SET embedding_model = 'incompatible-model' WHERE id = %s",
                (VALID_ID,),
            )
    pgvector_backend._initialized = False

    with pytest.raises(RuntimeError, match="incompatible with MEMORY_EMBEDDING_MODEL"):
        pgvector_backend.init()


def test_shared_missing_and_invalid_id_contract():
    assert_get_row_not_found(pgvector_backend)
    assert_delete_raises_if_missing(pgvector_backend)
    assert_invalid_id_rejected(pgvector_backend)


def test_add_get_list_and_delete_round_trip():
    store = pgvector_backend.get_vectorstore(FakeEmbeddings())
    document = Document(
        page_content="Python service architecture",
        metadata=_metadata(VALID_ID, tags=["python", "architecture"]),
    )

    assert store.add_documents([document], ids=[VALID_ID]) == [VALID_ID]
    row = pgvector_backend.get_row(VALID_ID)
    assert row is not None
    assert row["text"] == "Python service architecture"
    assert row["metadata"]["repo"] == "repo"
    assert pgvector_backend.list_rows(repo="repo") == [row]
    assert pgvector_backend.load_all() == [row]

    pgvector_backend.delete_row(VALID_ID)
    assert pgvector_backend.get_row(VALID_ID) is None


def test_exact_cosine_search_preserves_score_order():
    store = pgvector_backend.get_vectorstore(FakeEmbeddings())
    weather_id = "00000000-0000-0000-0000-000000000002"
    store.add_documents(
        [
            Document(page_content="Python code", metadata=_metadata(VALID_ID)),
            Document(page_content="weather report", metadata=_metadata(weather_id)),
        ],
        ids=[VALID_ID, weather_id],
    )

    results = store.similarity_search_with_relevance_scores("Python", k=2)

    assert [doc.metadata["id"] for doc, _ in results] == [VALID_ID, weather_id]
    assert results[0][1] == pytest.approx(1.0)
    assert results[1][1] == pytest.approx(0.0)


def test_wrong_embedding_dimension_crashes_before_insert():
    store = pgvector_backend.get_vectorstore(FakeEmbeddings(dimension=3))
    with pytest.raises(ValueError, match="returned 3 dimensions"):
        store.add_documents(
            [Document(page_content="wrong size", metadata=_metadata(VALID_ID))],
            ids=[VALID_ID],
        )
    assert pgvector_backend.get_row(VALID_ID) is None


def test_high_level_update_is_atomic_and_keeps_one_row():
    id = memory_db.add("original content", repo="r", tags=["before"])
    original = memory_db.get(id)

    memory_db.update(id, content="updated content", tags=["after"])

    updated = memory_db.get(id)
    assert updated is not None
    assert updated["content"] == "updated content"
    assert updated["tags"] == ["after"]
    assert updated["created_at"] == original["created_at"]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM memories WHERE id = %s", (id,))
            assert cur.fetchone() == (1,)


def test_failed_update_preserves_persisted_and_in_memory_document():
    id = memory_db.add("original content", repo="r")
    retriever = memory_db._get_retriever()
    memory_db._embeddings.fail_on = "will fail"

    with pytest.raises(RuntimeError, match="synthetic embedding failure"):
        memory_db.update(id, content="will fail")

    assert memory_db.get(id)["content"] == "original content"
    stream_matches = [
        doc for doc in retriever.memory_stream if doc.metadata.get("id") == id
    ]
    assert len(stream_matches) == 1
    assert stream_matches[0].page_content == "original content"


def test_reloaded_time_weighted_search_prefers_recent_memory():
    store = pgvector_backend.get_vectorstore(FakeEmbeddings())
    recent_id = "00000000-0000-0000-0000-000000000002"
    old_time = datetime.now(timezone.utc) - timedelta(days=30)
    recent_time = datetime.now(timezone.utc)
    old_metadata = _metadata(VALID_ID)
    old_metadata.update(
        {
            "created_at": old_time.isoformat(),
            "updated_at": old_time.isoformat(),
            "last_accessed_at": old_time.isoformat(),
        }
    )
    recent_metadata = _metadata(recent_id)
    recent_metadata.update(
        {
            "created_at": recent_time.isoformat(),
            "updated_at": recent_time.isoformat(),
            "last_accessed_at": recent_time.isoformat(),
        }
    )
    store.add_documents(
        [
            Document(page_content="Python architecture", metadata=old_metadata),
            Document(page_content="Python architecture", metadata=recent_metadata),
        ],
        ids=[VALID_ID, recent_id],
    )

    memory_db._retriever = None
    results = memory_db.search("Python architecture")

    assert [result["id"] for result in results[:2]] == [recent_id, VALID_ID]
    assert all(
        doc.metadata["last_accessed_at"].tzinfo is None
        for doc in memory_db._get_retriever().memory_stream
    )


def test_high_level_search_applies_repo_and_tag_filters():
    matching_id = memory_db.add(
        "Python architecture", repo="agent-smith", tags=["python", "architecture"]
    )
    memory_db.add("Python testing", repo="other", tags=["python"])

    results = memory_db.search(
        "Python", repo="agent-smith", tags=["architecture"]
    )

    assert [result["id"] for result in results] == [matching_id]
