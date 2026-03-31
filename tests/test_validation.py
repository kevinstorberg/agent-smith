from __future__ import annotations


import pytest

from scripts.shared.validation import (
    assert_not_empty,
    validate_memory_id,
    require_env,
    extract_memory_metadata,
)


class TestAssertNotEmpty:
    def test_passes_on_nonempty_string(self):
        assert_not_empty("hello", "name")

    def test_raises_on_empty_string(self):
        with pytest.raises(AssertionError, match="name must not be empty"):
            assert_not_empty("", "name")

    def test_raises_on_none(self):
        with pytest.raises(AssertionError, match="field must not be empty"):
            assert_not_empty(None, "field")

    def test_raises_on_empty_list(self):
        with pytest.raises(AssertionError):
            assert_not_empty([], "ids")


class TestValidateMemoryId:
    def test_accepts_valid_uuid(self):
        validate_memory_id("12345678-1234-1234-1234-123456789abc")

    def test_rejects_invalid_format(self):
        with pytest.raises(ValueError, match="Invalid memory ID"):
            validate_memory_id("not-a-uuid")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_memory_id("")


class TestRequireEnv:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "hello")
        assert require_env("TEST_VAR") == "hello"

    def test_raises_when_missing(self, monkeypatch):
        monkeypatch.delenv("TEST_VAR", raising=False)
        with pytest.raises(SystemExit):
            require_env("TEST_VAR")

    def test_raises_with_hint(self, monkeypatch):
        monkeypatch.delenv("TEST_VAR", raising=False)
        with pytest.raises(SystemExit, match="Set it"):
            require_env("TEST_VAR", hint="Set it in .env")


class TestExtractMemoryMetadata:
    def test_extracts_fields(self):
        row = {"metadata": {"repo": "my-repo", "tags": '["a","b"]', "created_at": "2026-01-01"}}
        result = extract_memory_metadata(row)
        assert result["repo"] == "my-repo"
        assert result["tags"] == '["a","b"]'

    def test_handles_missing_metadata(self):
        result = extract_memory_metadata({})
        assert result["repo"] == ""
        assert result["tags"] == "[]"

    def test_handles_missing_keys(self):
        result = extract_memory_metadata({"metadata": {}})
        assert result["repo"] == ""
        assert result["created_at"] == ""
