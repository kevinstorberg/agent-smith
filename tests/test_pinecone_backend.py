from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import services.memory.backends.pinecone_backend as pb
from tests.shared_backend_contract import (
    VALID_ID, MISSING_ID,
    assert_get_row_not_found, assert_delete_raises_if_missing, assert_invalid_id_rejected,
)


@pytest.fixture(autouse=True)
def reset_globals():
    pb._pc = None
    pb._index = None
    yield
    pb._pc = None
    pb._index = None


@pytest.fixture
def mock_index():
    index = MagicMock()
    index.describe_index_stats.return_value = {"total_vector_count": 0}
    index.fetch.return_value = {"vectors": {}}
    index.query.return_value = {"matches": []}
    return index


@pytest.fixture
def mock_pc(mock_index):
    pc = MagicMock()
    pc.has_index.return_value = True
    pc.Index.return_value = mock_index
    with patch.object(pb, "_get_pc", return_value=pc):
        yield pc


def test_init_connects(mock_pc):
    pb.init()
    mock_pc.has_index.assert_called_once()


def test_get_row_found(mock_pc, mock_index):
    mock_index.fetch.return_value = {
        "vectors": {VALID_ID: {"metadata": {"text": "hello", "repo": "test"}}}
    }
    row = pb.get_row(VALID_ID)
    assert row["id"] == VALID_ID
    assert row["text"] == "hello"


def test_get_row_not_found(mock_pc, mock_index):
    assert_get_row_not_found(pb)


def test_delete_row_raises_if_missing(mock_pc, mock_index):
    assert_delete_raises_if_missing(pb)


def test_delete_row_calls_delete(mock_pc, mock_index):
    mock_index.fetch.return_value = {
        "vectors": {VALID_ID: {"metadata": {"text": "hello"}}}
    }
    pb.delete_row(VALID_ID)
    mock_index.delete.assert_called_once_with(ids=[VALID_ID])


def test_invalid_id_rejected(mock_pc):
    assert_invalid_id_rejected(pb)
