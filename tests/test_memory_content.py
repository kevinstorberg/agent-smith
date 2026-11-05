from __future__ import annotations

import logging
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.documents import Document

from services.db import get_connection
from services.memory import db
from services.memory.backends import lancedb_backend, pgvector_backend, pinecone_backend
from services.memory.content import (
    limit_memory_content,
    memory_word_count,
    normalize_memory_content,
)
from tests.test_pgvector_backend import FakeEmbeddings

CREATED = "2026-01-27T15:30:00+00:00"
PREFIX = " \n" + " \t".join(f"word{index}" for index in range(250))
OVERSIZED = PREFIX + "\u2003PRIVATE_DISCARDED_TAIL"


def legacy_metadata(id):
    return {
        "id": id,
        "repo": "",
        "tags": "[]",
        "created_at": CREATED,
        "updated_at": CREATED,
        "last_accessed_at": CREATED,
        "buffer_idx": 0,
        "source_type": "general",
        "source_id": id,
    }


class RecordingEmbeddings(FakeEmbeddings):
    def __init__(self):
        super().__init__()
        self.documents = []

    def embed_documents(self, texts):
        self.documents.extend(texts)
        return super().embed_documents(texts)


class SyntheticPineconeIndex:
    config = SimpleNamespace(host="synthetic.invalid", api_key="synthetic")

    def __init__(self):
        self.rows = {}

    def fetch(self, ids, **kwargs):
        return {
            "vectors": {
                key: deepcopy(self.rows[key]) for key in ids if key in self.rows
            }
        }

    def query(self, **kwargs):
        return {
            "matches": [
                {"id": key, "metadata": deepcopy(row["metadata"])}
                for key, row in self.rows.items()
            ]
        }

    def upsert(self, vectors, **kwargs):
        for key, values, metadata in vectors:
            self.rows[key] = {
                "values": deepcopy(values),
                "metadata": deepcopy(metadata),
            }
        return SimpleNamespace(get=lambda: None)


@pytest.fixture(
    params=[lancedb_backend, pgvector_backend, pinecone_backend],
    ids=["lancedb", "pgvector", "pinecone-adapter"],
)
def content_store(request, monkeypatch, tmp_path):
    backend = request.param
    monkeypatch.setattr(db, "get_backend", lambda: backend)
    monkeypatch.setattr(lancedb_backend, "STORE_PATH", tmp_path / "memories")
    monkeypatch.setattr(pgvector_backend, "_initialized", False)
    monkeypatch.setattr(pinecone_backend, "_get_index", lambda: index)
    index = SyntheticPineconeIndex()
    embeddings = RecordingEmbeddings()
    monkeypatch.setattr(db, "_embeddings", embeddings)
    monkeypatch.setattr(db, "_retriever", None)
    if backend is pgvector_backend:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM memories")
    yield backend, embeddings
    if backend is pgvector_backend:
        with get_connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM memories")


@pytest.mark.parametrize("count", [249, 250])
def test_short_memory_text_is_preserved_exactly(count):
    content = (
        " \n" + "\u2003\t".join(f"naïve-{index}!" for index in range(count)) + " \r\n"
    )
    assert memory_word_count(content) == count
    assert limit_memory_content(content) == content


def test_long_memory_keeps_original_prefix_and_complete_unicode_word():
    content = PREFIX.removesuffix("word249") + "café—東京" + "\u00a0removed"
    assert limit_memory_content(content) == PREFIX.removesuffix("word249") + "café—東京"
    assert memory_word_count(limit_memory_content(content)) == 250
    assert limit_memory_content("a\tb\nc", max_words=2) == "a\tb"


@pytest.mark.parametrize("budget", [0, -1, 251, True, None, 1.5, "250"])
def test_memory_budget_is_explicit_and_cannot_bypass_record_limit(budget):
    with pytest.raises(ValueError, match="word budget"):
        limit_memory_content("valid", max_words=budget)


def test_truncation_notice_contains_only_word_counts(caplog):
    with caplog.at_level(logging.INFO, logger="agent_smith.memory.content"):
        assert normalize_memory_content(OVERSIZED) == PREFIX
    assert len(caplog.records) == 1
    assert (
        caplog.records[0].getMessage()
        == "Memory content truncated original_words=251 final_words=250"
    )
    assert "PRIVATE" not in caplog.text and "word0" not in caplog.text


@pytest.mark.parametrize(
    "operation,value",
    [
        (operation, value)
        for operation in ("add", "publish", "update")
        for value in (None, 123, {}, "", " \t\u2003")
        if operation != "update" or value is not None
    ],
)
def test_invalid_content_fails_before_any_backend_or_embedding(
    operation, value, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid content reached I/O")

    monkeypatch.setattr(db, "get_backend", forbidden)
    monkeypatch.setattr(db, "_get_retriever", forbidden)
    with pytest.raises(ValueError):
        if operation == "publish":
            db.publish(str(uuid4()), value, created_at=CREATED)
        elif operation == "update":
            db.update(str(uuid4()), content=value)
        else:
            db.add(value)


@pytest.mark.parametrize("operation", ["add", "update", "publish"])
@pytest.mark.parametrize("count", [249, 250, 251])
def test_each_write_embeds_and_stores_the_same_canonical_text(
    content_store, operation, count
):
    backend, embeddings = content_store
    content = " \n" + " \t".join(f"word{index}" for index in range(count)) + " \n"
    expected = PREFIX if count == 251 else content
    id = str(uuid4())
    if operation == "update":
        id = db.add("Original")
        created = backend.get_row(id)["metadata"]["created_at"]
        embeddings.documents.clear()
        db.update(id, content=content)
        assert backend.get_row(id)["metadata"]["created_at"] == created
    elif operation == "publish":
        db.publish(id, content, created_at=CREATED)
    else:
        id = db.add(content)
    assert backend.get_row(id)["text"] == expected
    assert embeddings.documents == [expected]
    if db._retriever is not None:
        assert (
            next(
                item.page_content
                for item in db._retriever.memory_stream
                if item.metadata["id"] == id
            )
            == expected
        )


def test_metadata_only_update_caps_legacy_content_without_changing_identity(
    content_store,
):
    backend, embeddings = content_store
    id = str(uuid4())
    store = backend.get_vectorstore(embeddings)
    store.add_documents(
        [Document(page_content=OVERSIZED, metadata=legacy_metadata(id))], ids=[id]
    )
    embeddings.documents.clear()
    db.update(id, tags=["updated"])
    saved = backend.get_row(id)
    assert saved["text"] == PREFIX
    assert saved["id"] == id and saved["metadata"]["created_at"] == CREATED
    assert embeddings.documents == [PREFIX]


def test_independent_additions_keep_independent_ids_with_equal_canonical_text(
    content_store,
):
    backend, _ = content_store
    first, second = db.add(OVERSIZED), db.add(PREFIX + " DIFFERENT_TAIL")
    assert first != second
    assert backend.get_row(first)["text"] == backend.get_row(second)["text"] == PREFIX


def test_exact_legacy_publication_replay_never_rewrites_oversized_stored_text(
    content_store, monkeypatch
):
    backend, embeddings = content_store
    id = str(uuid4())
    backend.get_vectorstore(embeddings).add_documents(
        [Document(page_content=OVERSIZED, metadata=legacy_metadata(id))], ids=[id]
    )
    before = deepcopy(backend.get_row(id))
    embeddings.documents.clear()

    def forbidden(*args, **kwargs):
        raise AssertionError("Exact historical replay must not write")

    monkeypatch.setattr(backend, "get_vectorstore", forbidden)
    assert db.publish(id, OVERSIZED, created_at=CREATED) == id
    assert backend.get_row(id) == before
    assert embeddings.documents == []


def test_canonical_long_publication_replay_does_not_embed_or_write_again(content_store):
    backend, embeddings = content_store
    id = str(uuid4())
    assert db.publish(id, OVERSIZED, created_at=CREATED) == id
    before = deepcopy(backend.get_row(id))
    assert db.publish(id, OVERSIZED, created_at=CREATED) == id
    assert db.publish(id, PREFIX + " OTHER_DISCARDED_SUFFIX", created_at=CREATED) == id
    assert backend.get_row(id) == before
    assert embeddings.documents == [PREFIX]


def test_legacy_prefix_match_alone_is_a_conflict_without_mutation(content_store):
    backend, embeddings = content_store
    id = str(uuid4())
    backend.get_vectorstore(embeddings).add_documents(
        [Document(page_content=OVERSIZED, metadata=legacy_metadata(id))], ids=[id]
    )
    before = deepcopy(backend.get_row(id))
    embeddings.documents.clear()
    with pytest.raises(db.MemoryConflictError):
        db.publish(id, PREFIX + " DIFFERENT_SUFFIX", created_at=CREATED)
    assert backend.get_row(id) == before
    assert embeddings.documents == []
