import importlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.tools import TOOL_FACTORY, _auto_import_tools, _should_auto_import, load_tools, register_tool
from src.tools.context import ToolContext


@pytest.mark.unit
class TestToolRegistry:
    def test_template_does_not_register_demo_tools(self):
        assert "test_auto" not in TOOL_FACTORY

    def test_should_auto_import_skips_private_and_context_modules(self):
        assert _should_auto_import("project_search")
        assert not _should_auto_import("_example")
        assert not _should_auto_import("context")

    def test_auto_import_registers_app_tool_module(self, monkeypatch, tmp_path):
        package_dir = tmp_path / "app_tools"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("")
        (package_dir / "project_tool.py").write_text(
            "\n".join(
                [
                    "from src.tools import register_tool",
                    "",
                    '@register_tool("project_tool")',
                    "def create_project_tool(context):",
                    "    return None",
                    "",
                ]
            )
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        TOOL_FACTORY.pop("project_tool", None)

        try:
            _auto_import_tools("app_tools", package_dir)
            assert "project_tool" in TOOL_FACTORY
        finally:
            TOOL_FACTORY.pop("project_tool", None)
            sys.modules.pop("app_tools.project_tool", None)
            sys.modules.pop("app_tools", None)

    def test_imports_with_uvloop_event_loop(self):
        code = """
import asyncio
import uvloop

loop = uvloop.new_event_loop()
asyncio.set_event_loop(loop)
try:
    import src.tools as tools
    assert "test_auto" not in tools.TOOL_FACTORY
finally:
    loop.close()
"""
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)

        assert result.returncode == 0, result.stderr

    def test_register_tool_adds_to_factory(self):
        @register_tool("test_tool_reg")
        def create_test_tool(context):
            return None

        assert "test_tool_reg" in TOOL_FACTORY

    def test_load_tools_unknown_raises(self):
        ctx = ToolContext(enabled_sources=[], source_limits={})
        with pytest.raises(ValueError, match="Unknown tool"):
            load_tools(["nonexistent_tool_xyz_99"], ctx)

    def test_load_tools_filters_none(self):
        @register_tool("disabled_tool_test")
        def create_disabled(context):
            return None

        ctx = ToolContext(enabled_sources=[], source_limits={})
        tools = load_tools(["disabled_tool_test"], ctx)
        assert tools == []

    def test_load_tools_includes_non_none(self):
        class FakeTool:
            name = "fake"

        @register_tool("enabled_tool_test")
        def create_enabled(context):
            return FakeTool()

        ctx = ToolContext(enabled_sources=[], source_limits={})
        tools = load_tools(["enabled_tool_test"], ctx)
        assert len(tools) == 1
        assert tools[0].name == "fake"

    def test_tool_context_from_graph_config_copies_graph_name_and_tools(self):
        graph_config = SimpleNamespace(name="workflow-a", tools=["tool-a", "tool-b"])

        context = ToolContext.from_graph_config(graph_config)

        assert context.graph_name == "workflow-a"
        assert context.tools == ["tool-a", "tool-b"]
        assert context.enabled_sources == []
        assert context.source_limits == {}
        assert context.scope is None
