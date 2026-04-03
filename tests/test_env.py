from __future__ import annotations

import os
from pathlib import Path

from scripts.shared.env import expand_env, load_dotenv


def test_load_dotenv_reads_file(tmp_path: Path, monkeypatch: object):
    monkeypatch.delenv("MY_TEST_VAR", raising=False)
    (tmp_path / ".env.test").write_text("MY_TEST_VAR=hello\n")
    load_dotenv(tmp_path)
    assert os.environ["MY_TEST_VAR"] == "hello"


def test_load_dotenv_skips_comments_and_blanks(tmp_path: Path, monkeypatch: object):
    monkeypatch.delenv("X", raising=False)
    (tmp_path / ".env.test").write_text("# comment\n\n  \nX=1\n")
    load_dotenv(tmp_path)
    assert os.environ["X"] == "1"


def test_load_dotenv_does_not_override(tmp_path: Path, monkeypatch: object):
    monkeypatch.setenv("EXISTING", "original")
    (tmp_path / ".env.test").write_text("EXISTING=overwritten\n")
    load_dotenv(tmp_path)
    assert os.environ["EXISTING"] == "original"


def test_load_dotenv_strips_quotes(tmp_path: Path, monkeypatch: object):
    monkeypatch.delenv("Q", raising=False)
    (tmp_path / ".env.test").write_text("Q='quoted'\n")
    load_dotenv(tmp_path)
    assert os.environ["Q"] == "quoted"


def test_load_dotenv_missing_file(tmp_path: Path):
    load_dotenv(tmp_path)


def test_expand_env_string(monkeypatch: object):
    monkeypatch.setenv("TOKEN", "abc123")
    assert expand_env("Bearer ${TOKEN}") == "Bearer abc123"


def test_expand_env_unset_passes_through():
    assert expand_env("${DEFINITELY_NOT_SET_XYZ}") == "${DEFINITELY_NOT_SET_XYZ}"


def test_expand_env_dict(monkeypatch: object):
    monkeypatch.setenv("V", "val")
    result = expand_env({"key": "${V}", "nested": {"inner": "${V}"}})
    assert result == {"key": "val", "nested": {"inner": "val"}}


def test_expand_env_list(monkeypatch: object):
    monkeypatch.setenv("V", "x")
    assert expand_env(["${V}", "literal"]) == ["x", "literal"]


def test_expand_env_non_string():
    assert expand_env(42) == 42
    assert expand_env(None) is None
