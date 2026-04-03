from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.api.routers.base import require_found, list_response


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
