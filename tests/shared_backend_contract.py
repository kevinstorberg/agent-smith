from __future__ import annotations

import pytest

VALID_ID = "00000000-0000-0000-0000-000000000001"
MISSING_ID = "00000000-0000-0000-0000-000000000099"


def assert_get_row_not_found(backend, row_id: str = MISSING_ID):
    assert backend.get_row(row_id) is None


def assert_delete_raises_if_missing(backend, row_id: str = MISSING_ID):
    with pytest.raises(KeyError):
        backend.delete_row(row_id)


def assert_invalid_id_rejected(backend):
    with pytest.raises(ValueError):
        backend.get_row("not-a-uuid")
