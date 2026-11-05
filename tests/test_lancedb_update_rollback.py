from __future__ import annotations

from copy import deepcopy

import pytest

from services.memory import db
from services.memory.backends import lancedb_backend
from tests.test_memory_content import content_store as content_store

pytestmark = pytest.mark.parametrize(
    "content_store", [lancedb_backend], indirect=True, ids=["lancedb"]
)


def native_snapshot():
    table = lancedb_backend._get_table()
    assert table is not None
    return table.to_arrow().sort_by([("id", "ascending")])


@pytest.mark.parametrize(
    "has_neighbor", [False, True], ids=["sole-row", "neighboring-row"]
)
def test_failed_replacement_restores_native_rows_vectors_schema_and_cache(
    content_store, monkeypatch, has_neighbor
):
    backend, embeddings = content_store
    assert backend._get_table() is None
    original_id = db.add("Original", repo="rollback-tests", tags=["keep"])
    if has_neighbor:
        db.add("Neighbor", repo="other-scope", tags=["unrelated"])
    before = native_snapshot()
    original = deepcopy(backend.get_row(original_id))
    retriever = db._get_retriever()
    stream = retriever.memory_stream
    documents = tuple(stream)
    contents = deepcopy(stream)
    embeddings.documents.clear()
    embeddings.fail_on = "Replacement"
    embed_documents = embeddings.embed_documents
    observed_tables, failures = [], []

    def record_embedding_failure(texts):
        table = backend._get_table()
        observed_tables.append((table is not None, bool(table), table.count_rows()))
        try:
            return embed_documents(texts)
        except RuntimeError as error:
            failures.append(error)
            raise

    monkeypatch.setattr(embeddings, "embed_documents", record_embedding_failure)
    with pytest.raises(RuntimeError, match="synthetic embedding failure") as raised:
        db.update(
            original_id,
            content="Replacement",
            repo="replacement-scope",
            tags=["replacement"],
        )

    assert len(failures) == 1 and raised.value is failures[0]
    assert observed_tables == [(True, has_neighbor, int(has_neighbor))]
    assert backend.get_row(original_id) == original
    assert native_snapshot().equals(before, check_metadata=True)
    assert db._retriever is retriever
    assert retriever.memory_stream is stream
    assert stream == contents
    assert len(stream) == len(documents)
    assert all(
        current is previous for current, previous in zip(stream, documents, strict=True)
    )
    assert embeddings.documents == ["Replacement"]


def test_successful_sole_row_replacement_preserves_identity_schema_and_embeds_new_text(
    content_store,
):
    backend, embeddings = content_store
    assert backend._get_table() is None
    original_id = db.add("Original", repo="rollback-tests", tags=["keep"])
    before = native_snapshot()
    original = deepcopy(backend.get_row(original_id))
    embeddings.documents.clear()

    db.update(original_id, content="Weather replacement")

    saved = backend.get_row(original_id)
    after = native_snapshot()
    assert after.num_rows == 1
    assert after.schema.equals(before.schema, check_metadata=True)
    assert saved["id"] == original_id and saved["text"] == "Weather replacement"
    assert saved["metadata"]["created_at"] == original["metadata"]["created_at"]
    assert saved["metadata"]["repo"] == "rollback-tests"
    assert saved["metadata"]["tags"] == original["metadata"]["tags"]
    assert after.to_pylist()[0]["vector"] == embeddings.embed_query(
        "Weather replacement"
    )
    assert after.to_pylist()[0]["vector"] != before.to_pylist()[0]["vector"]
    assert db._retriever.memory_stream[0].page_content == "Weather replacement"
    assert embeddings.documents == ["Weather replacement"]
