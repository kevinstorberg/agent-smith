from __future__ import annotations


import pytest

from scripts.shared.validation import (
    assert_not_empty,
    validate_memory_id,
    require_env,
    extract_memory_metadata,
    validate_item_name,
    validate_repo_format,
    validate_agents_list,
    validate_postgres_url,
    empty_to_none,
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


class TestValidateItemName:
    def test_accepts_lowercase_with_underscores(self):
        assert validate_item_name("my_rule") == "my_rule"

    def test_accepts_single_letter(self):
        assert validate_item_name("a") == "a"

    def test_accepts_letter_and_digits(self):
        assert validate_item_name("a1") == "a1"

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError, match="lowercase"):
            validate_item_name("MyRule")

    def test_rejects_starts_with_digit(self):
        with pytest.raises(ValueError, match="lowercase"):
            validate_item_name("123abc")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="lowercase"):
            validate_item_name("has space")

    def test_rejects_hyphens(self):
        with pytest.raises(ValueError, match="lowercase"):
            validate_item_name("has-hyphen")


class TestValidateRepoFormat:
    def test_accepts_wildcard(self):
        assert validate_repo_format("*") == "*"

    def test_accepts_absolute_path(self):
        assert validate_repo_format("/abs/path") == "/abs/path"

    def test_rejects_relative_path(self):
        with pytest.raises(ValueError, match="absolute path"):
            validate_repo_format("relative/path")


class TestValidateAgentsList:
    def test_accepts_valid_agents(self):
        result = validate_agents_list(["claude"], ["claude", "codex"])
        assert result == ["claude"]

    def test_accepts_empty_list(self):
        result = validate_agents_list([], ["claude"])
        assert result == []

    def test_rejects_unknown_agent(self):
        with pytest.raises(ValueError, match="Invalid agents"):
            validate_agents_list(["unknown"], ["claude", "codex"])


class TestValidatePostgresUrl:
    def test_accepts_postgresql_scheme(self):
        validate_postgres_url("postgresql://localhost/db")

    def test_accepts_postgres_scheme(self):
        validate_postgres_url("postgres://localhost/db")

    def test_rejects_sqlite(self):
        with pytest.raises(ValueError, match="postgresql://"):
            validate_postgres_url("sqlite:///test.db")

    def test_rejects_mysql(self):
        with pytest.raises(ValueError, match="postgresql://"):
            validate_postgres_url("mysql://localhost/db")


class TestEmptyToNone:
    def test_empty_string_returns_none(self):
        assert empty_to_none("") is None

    def test_nonempty_returns_value(self):
        assert empty_to_none("hello") == "hello"
