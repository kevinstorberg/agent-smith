from __future__ import annotations

from pathlib import Path

from scripts.shared.fs import atomic_write, compose_strings, extract_brief


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
