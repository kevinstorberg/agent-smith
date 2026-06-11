from __future__ import annotations

from services.api.models.shared.harness import upsert_item
from services.api.routers.tools import ToolsRouter
from services.config import ALL_AGENTS
from tests.conftest import harness_cleanup

TOOL_CONTENT = {"body": "", "metadata": {"url": "https://example.com"}}

_clean = harness_cleanup("api_filter_%")


def test_tools_endpoint_without_project_filter_returns_project_scoped_items():
    upsert_item("tool", "api_filter_global", content=TOOL_CONTENT, agents=ALL_AGENTS)
    upsert_item(
        "tool",
        "api_filter_project",
        content=TOOL_CONTENT,
        agents=ALL_AGENTS,
        project="review-service",
    )

    response = ToolsRouter().list_items(project="", agent="", name="", limit=100, offset=0)
    names = {item["name"] for item in response["items"]}

    assert "api_filter_global" in names
    assert "api_filter_project" in names


def test_tools_endpoint_project_filter_excludes_other_projects():
    upsert_item("tool", "api_filter_global", content=TOOL_CONTENT, agents=ALL_AGENTS)
    upsert_item(
        "tool",
        "api_filter_review",
        content=TOOL_CONTENT,
        agents=ALL_AGENTS,
        project="review-service",
    )
    upsert_item(
        "tool",
        "api_filter_other",
        content=TOOL_CONTENT,
        agents=ALL_AGENTS,
        project="other-service",
    )

    response = ToolsRouter().list_items(project="review-service", agent="", name="", limit=100, offset=0)
    names = {item["name"] for item in response["items"]}

    assert "api_filter_global" in names
    assert "api_filter_review" in names
    assert "api_filter_other" not in names
