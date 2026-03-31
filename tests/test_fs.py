from __future__ import annotations

from pathlib import Path

from scripts.shared.fs import atomic_write, compose_strings, extract_brief, _compose_agent_file


def test_compose_strings_preserves_order():
    items = [("a", "first"), ("b", "second")]
    result = compose_strings(items)
    assert result.index("first") < result.index("second")


def test_compose_strings_with_transform():
    items = [("a", "hello")]
    result = compose_strings(items, transform=lambda text, name: text.upper())
    assert "HELLO" in result


def test_extract_brief_strips_process():
    content = "## Rule\n* **The Rule:** Be good.\n* **Your Process:**\n    1. Step one."
    result = extract_brief(content, Path("~/.claude/rules/test.md"))
    assert "Step one" not in result
    assert "See `~/.claude/rules/test.md`" in result


def test_extract_brief_passthrough_no_marker():
    content = "## Constraints\n* Be concise."
    result = extract_brief(content, Path("~/.claude/rules/test.md"))
    assert result == content


def test_atomic_write_creates_file(tmp_path: Path):
    path = tmp_path / "out.txt"
    changed, msg = atomic_write(path, "hello")
    assert changed is True
    assert path.read_text() == "hello"
    assert "updated" in msg


def test_atomic_write_skips_unchanged(tmp_path: Path):
    path = tmp_path / "out.txt"
    path.write_text("hello")
    changed, msg = atomic_write(path, "hello")
    assert changed is False
    assert "unchanged" in msg


def test_compose_agent_file_with_metadata():
    body = "You are a code reviewer."
    metadata = {"description": "Reviews code", "model": "sonnet"}
    result = _compose_agent_file(body, metadata)
    assert result.startswith("---\n")
    assert "description: Reviews code" in result
    assert "model: sonnet" in result
    assert "You are a code reviewer." in result


def test_compose_agent_file_no_metadata():
    body = "You are a helper."
    result = _compose_agent_file(body, {})
    assert result.strip() == "You are a helper."
    assert "---" not in result


def test_compose_agent_file_with_scoped_rules():
    body = "Agent prompt."
    metadata = {"description": "test"}
    rules = [{"content": {"body": "## Rule 1\nBe good."}}]
    result = _compose_agent_file(body, metadata, scoped_rules=rules)
    assert "# Rules" in result
    assert "## Rule 1" in result


def test_compose_agent_file_no_scoped_rules():
    body = "Agent prompt."
    metadata = {"description": "test"}
    result = _compose_agent_file(body, metadata, scoped_rules=None)
    assert "# Rules" not in result
