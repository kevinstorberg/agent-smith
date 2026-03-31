from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.db.base_model import BaseModel


class TestSerializeTimestamps:
    def test_converts_datetime_fields(self):
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        row = {"id": 1, "created_at": now, "updated_at": now, "name": "test"}
        result = BaseModel.serialize_timestamps(row)
        assert result["created_at"] == now.isoformat()
        assert result["updated_at"] == now.isoformat()
        assert result["name"] == "test"

    def test_skips_none_fields(self):
        row = {"id": 1, "created_at": None, "updated_at": None}
        result = BaseModel.serialize_timestamps(row)
        assert result["created_at"] is None

    def test_handles_missing_fields(self):
        row = {"id": 1, "name": "test"}
        result = BaseModel.serialize_timestamps(row)
        assert "created_at" not in result

    def test_handles_timestamp_field(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row = {"timestamp": now}
        result = BaseModel.serialize_timestamps(row)
        assert result["timestamp"] == now.isoformat()

    def test_does_not_mutate_original(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        row = {"created_at": now}
        BaseModel.serialize_timestamps(row)
        assert isinstance(row["created_at"], datetime)


class TestValidateId:
    def test_accepts_positive_id(self):
        from services.db.plans import PlanModel
        PlanModel._validate_id(1)

    def test_rejects_zero(self):
        from services.db.plans import PlanModel
        with pytest.raises(AssertionError):
            PlanModel._validate_id(0)

    def test_rejects_negative(self):
        from services.db.plans import PlanModel
        with pytest.raises(AssertionError):
            PlanModel._validate_id(-1)


class TestFindByIdAndDelete:
    @pytest.fixture(autouse=True)
    def _setup(self):
        from services.db import get_connection
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM plans")
        yield
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM plans")

    def test_find_by_id_returns_dict(self):
        from services.db.plans import create_plan
        plan_id = create_plan("test", "body")
        from services.db.plans import PlanModel
        result = PlanModel.find_by_id(plan_id)
        assert result is not None
        assert result["title"] == "test"
        assert isinstance(result["created_at"], str)

    def test_find_by_id_returns_none_for_missing(self):
        from services.db.plans import PlanModel
        assert PlanModel.find_by_id(99999) is None

    def test_delete_by_id_removes_row(self):
        from services.db.plans import create_plan, PlanModel
        plan_id = create_plan("to delete", "body")
        PlanModel.delete_by_id(plan_id)
        assert PlanModel.find_by_id(plan_id) is None
