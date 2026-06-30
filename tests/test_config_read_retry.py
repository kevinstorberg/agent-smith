"""Resilient reads of live destination config files during sync.

The destination files (~/.claude.json, etc.) are rewritten continuously by the
running agent app, so a read can catch the file mid-write (a torn read =
momentarily invalid JSON). read_with_retry heals that on the fly; genuine
corruption that survives the retry window crashes loudly without ever writing.
"""
from __future__ import annotations

import json

import pytest

from scripts.shared.agents import AGENT_TARGETS, ConfigUnreadableError, read_with_retry


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_file_reads_first_try(tmp_path):
    p = _write(tmp_path, "ok.json", json.dumps({"mcpServers": {"a": 1}}))
    assert read_with_retry(p, "json") == {"mcpServers": {"a": 1}}


def test_torn_read_heals_on_retry(tmp_path, monkeypatch):
    """A torn read on the first attempt is retried and succeeds (the fixable case)."""
    p = _write(tmp_path, "torn.json", json.dumps({"ok": True}))

    real_read = type(p).read_text
    calls = {"n": 0}

    def flaky_read(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return '{"ok": true'  # truncated mid-write -> JSONDecodeError
        return real_read(self, *a, **k)

    monkeypatch.setattr(type(p), "read_text", flaky_read)
    assert read_with_retry(p, "json", max_attempts=3, backoff=0) == {"ok": True}
    assert calls["n"] == 2  # retried exactly once, then clean


def test_persistent_corruption_crashes_after_n_attempts(tmp_path, monkeypatch):
    """Unfixable corruption raises ConfigUnreadableError after exhausting retries."""
    p = _write(tmp_path, "bad.json", '{"broken": ')

    calls = {"n": 0}
    real_read = type(p).read_text

    def counting_read(self, *a, **k):
        calls["n"] += 1
        return real_read(self, *a, **k)

    monkeypatch.setattr(type(p), "read_text", counting_read)
    with pytest.raises(ConfigUnreadableError) as exc:
        read_with_retry(p, "json", max_attempts=3, backoff=0)
    assert calls["n"] == 3
    assert str(p) in str(exc.value)


def test_corrupt_mcp_read_never_writes(tmp_path, monkeypatch):
    """sync_mcp must crash on an unreadable dest rather than overwrite (and erase) it."""
    dest = _write(tmp_path, "claude.json", '{"corrupt": ')
    original = dest.read_text(encoding="utf-8")

    from scripts.shared import mcp_utils
    from services.api.models import tool as tool_model

    monkeypatch.setitem(AGENT_TARGETS["claude"], "mcp_file", str(dest))
    monkeypatch.setattr(
        tool_model, "collect_tools_from_db", lambda agent: {"x": {"url": "http://x"}}
    )

    with pytest.raises(ConfigUnreadableError):
        mcp_utils.sync_mcp("claude", dry_run=False)

    assert dest.read_text(encoding="utf-8") == original  # untouched
