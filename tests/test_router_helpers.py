from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.api.routers.base import require_found, list_response, paginate, resolve_project, update_fields


def test_require_found_returns_item_when_truthy():
    item = {"id": 1, "name": "test"}
    assert require_found(item, "Rule", 1) == item


def test_require_found_raises_404_when_none():
    with pytest.raises(HTTPException) as exc_info:
        require_found(None, "Plan", 42)
    assert exc_info.value.status_code == 404
    assert "Plan not found: 42" in exc_info.value.detail


def test_require_found_raises_404_when_empty_dict():
    with pytest.raises(HTTPException) as exc_info:
        require_found({}, "Suite")
    assert exc_info.value.status_code == 404
    assert "Suite not found" in exc_info.value.detail


def test_require_found_raises_404_when_empty_list():
    with pytest.raises(HTTPException) as exc_info:
        require_found([], "Memory", "abc-123")
    assert exc_info.value.status_code == 404


def test_require_found_default_label():
    with pytest.raises(HTTPException) as exc_info:
        require_found(None)
    assert "Item not found" in exc_info.value.detail


def test_list_response_returns_correct_shape():
    result = list_response([{"id": 1}], 10)
    assert result == {"items": [{"id": 1}], "total": 10}


def test_list_response_empty():
    result = list_response([], 0)
    assert result == {"items": [], "total": 0}


class TestPaginate:
    def test_middle_slice(self):
        items, total = paginate([1, 2, 3, 4, 5], offset=1, limit=2)
        assert items == [2, 3]
        assert total == 5

    def test_from_start(self):
        items, total = paginate([1, 2, 3], offset=0, limit=2)
        assert items == [1, 2]
        assert total == 3

    def test_empty_list(self):
        items, total = paginate([], offset=0, limit=10)
        assert items == []
        assert total == 0

    def test_offset_beyond_end(self):
        items, total = paginate([1, 2], offset=5, limit=10)
        assert items == []
        assert total == 2


class TestResolveProject:
    def test_none_returns_unset(self):
        assert resolve_project(None) == "UNSET"

    def test_string_passes_through(self):
        assert resolve_project("my-proj") == "my-proj"

    def test_empty_string_passes_through(self):
        assert resolve_project("") == ""


class TestUpdateFields:
    def test_filters_none_values(self):
        from pydantic import BaseModel

        class Body(BaseModel):
            name: str | None = None
            enabled: bool | None = None

        result = update_fields(Body(name="test", enabled=None))
        assert result == {"name": "test"}

    def test_all_none_returns_empty(self):
        from pydantic import BaseModel

        class Body(BaseModel):
            name: str | None = None

        result = update_fields(Body())
        assert result == {}

    def test_all_set(self):
        from pydantic import BaseModel

        class Body(BaseModel):
            name: str | None = None
            enabled: bool | None = None

        result = update_fields(Body(name="x", enabled=True))
        assert result == {"name": "x", "enabled": True}
