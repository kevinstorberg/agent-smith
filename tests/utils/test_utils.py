import uuid
from datetime import datetime, timezone

import pytest

from src.utils.datetime import format_iso, parse_iso, utc_now
from src.utils.pagination import paginate
from src.utils.serialization import serialize_json


@pytest.mark.unit
class TestDatetimeUtils:
    def test_utc_now_is_timezone_aware(self):
        now = utc_now()
        assert now.tzinfo is not None
        assert now.tzinfo == timezone.utc

    def test_format_and_parse_roundtrip(self):
        now = utc_now()
        iso = format_iso(now)
        parsed = parse_iso(iso)
        assert parsed == now

    def test_parse_iso_handles_z_suffix(self):
        result = parse_iso("2024-01-15T10:30:00Z")
        assert result.tzinfo is not None


@pytest.mark.unit
class TestPagination:
    def test_paginate_limits_results(self):
        items = list(range(100))
        page = paginate(items, offset=10, limit=5)
        assert page.items == [10, 11, 12, 13, 14]
        assert page.total == 100
        assert page.offset == 10
        assert page.limit == 5

    def test_paginate_empty_list(self):
        page = paginate([], offset=0, limit=10)
        assert page.items == []
        assert page.total == 0

    def test_paginate_offset_beyond_end(self):
        items = [1, 2, 3]
        page = paginate(items, offset=10, limit=5)
        assert page.items == []
        assert page.total == 3


@pytest.mark.unit
class TestSerialization:
    def test_serializes_datetime(self):
        data = {"created": datetime(2024, 1, 1, tzinfo=timezone.utc)}
        result = serialize_json(data)
        assert "2024-01-01" in result

    def test_serializes_uuid(self):
        test_uuid = uuid.uuid4()
        data = {"id": test_uuid}
        result = serialize_json(data)
        assert str(test_uuid) in result

    def test_serializes_nested(self):
        data = {"items": [{"name": "test"}]}
        result = serialize_json(data)
        assert "test" in result
