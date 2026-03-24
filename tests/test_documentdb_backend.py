from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import services.memory.backends.documentdb_backend as db

VALID_ID = "00000000-0000-0000-0000-000000000001"
MISSING_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture(autouse=True)
def reset_globals():
    db._client = None
    db._collection = None
    yield
    db._client = None
    db._collection = None


@pytest.fixture
def mock_collection():
    coll = MagicMock()
    coll.name = "memories"
    coll.database = MagicMock()
    coll.count_documents.return_value = 0
    coll.find.return_value = iter([])
    coll.find_one.return_value = None
    coll.list_indexes.return_value = iter([])
    return coll


@pytest.fixture
def mock_client(mock_collection):
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=mock_db)
    with patch.object(db, "_get_client", return_value=client):
        yield client


def test_init_connects_and_creates_index(mock_client, mock_collection):
    mock_collection.list_indexes.return_value = iter([])
    with patch.object(db, "_embedding_dimensions", return_value=384):
        with patch.object(db.ScoredDocDBVectorSearch, "index_exists", return_value=False):
            with patch.object(db.ScoredDocDBVectorSearch, "create_index") as mock_create:
                db.init()
                mock_collection.create_index.assert_called_once()
                mock_create.assert_called_once()


def test_init_skips_index_when_exists(mock_client, mock_collection):
    with patch.object(db, "_embedding_dimensions", return_value=384):
        with patch.object(db.ScoredDocDBVectorSearch, "index_exists", return_value=True):
            with patch.object(db.ScoredDocDBVectorSearch, "create_index") as mock_create:
                db.init()
                mock_create.assert_not_called()


def test_get_row_found(mock_client, mock_collection):
    mock_collection.find_one.return_value = {
        "id": VALID_ID,
        db.TEXT_KEY: "hello world",
        "repo": "test",
        "tags": "[]",
    }
    row = db.get_row(VALID_ID)
    assert row["id"] == VALID_ID
    assert row["text"] == "hello world"
    assert row["metadata"]["repo"] == "test"


def test_get_row_not_found(mock_client, mock_collection):
    assert db.get_row(MISSING_ID) is None


def test_delete_row_success(mock_client, mock_collection):
    mock_result = MagicMock()
    mock_result.deleted_count = 1
    mock_collection.delete_one.return_value = mock_result
    db.delete_row(VALID_ID)
    mock_collection.delete_one.assert_called_once_with({"id": VALID_ID})


def test_delete_row_raises_if_missing(mock_client, mock_collection):
    mock_result = MagicMock()
    mock_result.deleted_count = 0
    mock_collection.delete_one.return_value = mock_result
    with pytest.raises(KeyError):
        db.delete_row(MISSING_ID)


def test_invalid_id_rejected(mock_client):
    with pytest.raises(ValueError):
        db.get_row("not-a-uuid")


def test_load_all_empty(mock_client, mock_collection):
    assert db.load_all() == []


def test_load_all_returns_formatted_rows(mock_client, mock_collection):
    mock_collection.count_documents.return_value = 1
    mock_cursor = MagicMock()
    mock_cursor.limit.return_value = iter([
        {"id": VALID_ID, db.TEXT_KEY: "content", "repo": "r", "tags": "[]"},
    ])
    mock_collection.find.return_value = mock_cursor
    rows = db.load_all()
    assert len(rows) == 1
    assert rows[0]["id"] == VALID_ID
    assert rows[0]["text"] == "content"
    assert "metadata" in rows[0]


def test_list_rows_filters_by_repo(mock_client, mock_collection):
    mock_cursor = MagicMock()
    mock_cursor.limit.return_value = iter([
        {"id": VALID_ID, db.TEXT_KEY: "content", "repo": "myrepo", "tags": "[]"},
    ])
    mock_collection.find.return_value = mock_cursor
    rows = db.list_rows(repo="myrepo", limit=10)
    mock_collection.find.assert_called_once()
    call_args = mock_collection.find.call_args
    assert call_args[0][0] == {"repo": "myrepo"}


def test_get_vectorstore_returns_subclass(mock_client, mock_collection):
    embeddings = MagicMock()
    store = db.get_vectorstore(embeddings)
    assert isinstance(store, db.ScoredDocDBVectorSearch)
