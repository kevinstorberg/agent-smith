from __future__ import annotations

import asyncio

import pytest

from services.graphs.server import mcp, run_graph


def test_server_name_uses_graphs_prefix():
    assert mcp.name.startswith("graphs")


def test_tools_list_contains_only_run_graph():
    tools = asyncio.run(mcp.list_tools())
    names = [t.name for t in tools]
    assert names == ["run_graph"]


def test_run_graph_tool_description_mentions_echo():
    tools = asyncio.run(mcp.list_tools())
    assert "echo" in tools[0].description


def test_echo_round_trip():
    result = asyncio.run(run_graph("echo", {"text": "hello"}))
    assert result == "hello"


def test_summarize_with_mock_llm(monkeypatch):
    from services.graphs.library import summarize

    class _Reply:
        content = "A short summary."

    class _FakeLLM:
        async def ainvoke(self, messages):
            return _Reply()

    monkeypatch.setattr(summarize, "init_chat_model", lambda **_: _FakeLLM())

    result = asyncio.run(run_graph("summarize", {"text": "Some long text to summarize."}))
    assert result == "A short summary."


def test_review_diff_invokes_read_file(monkeypatch, tmp_path):
    from services.graphs.library import review_diff

    diff_text = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
    diff_file = tmp_path / "test.diff"
    diff_file.write_text(diff_text)

    captured_user_msg = {}

    class _Reply:
        content = '{"summary": "Replaces old with new.", "observations": ["one-line edit"]}'

    class _FakeLLM:
        async def ainvoke(self, messages):
            for role, content in messages:
                if role == "user":
                    captured_user_msg["text"] = content
            return _Reply()

    monkeypatch.setattr(review_diff, "init_chat_model", lambda **_: _FakeLLM())

    result = asyncio.run(run_graph("review_diff", {"diff_path": str(diff_file)}))
    assert "summary" in result
    assert "observations" in result
    assert diff_text in captured_user_msg["text"], "review node must see the file content from the load node"


def test_summarize_propagates_llm_error(monkeypatch):
    from services.graphs.library import summarize

    class _FakeLLM:
        async def ainvoke(self, messages):
            raise RuntimeError("upstream LLM exploded")

    monkeypatch.setattr(summarize, "init_chat_model", lambda **_: _FakeLLM())

    with pytest.raises(RuntimeError, match="upstream LLM exploded"):
        asyncio.run(run_graph("summarize", {"text": "input"}))
