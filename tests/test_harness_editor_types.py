from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from services.harness import editor


def compose(
    kind, fields, *, metadata=None, body="", extensions=None, dirty=None, **settings
):
    original = {"body": body, "metadata": metadata or {}}
    baseline = editor.decode(kind, "sample", original)
    return editor.compose(
        kind,
        "sample",
        fields={**baseline["fields"], **fields},
        extensions=extensions if extensions is not None else baseline["extensions"],
        original_content=original,
        dirty_paths=dirty
        if dirty is not None
        else ["/fields/" + key for key in fields],
        **settings,
    )


def test_all_five_kinds_are_described_with_examples_and_canonical_hook_events():
    from services.api.models.hook import HOOK_EVENT_MAP

    kinds = editor.descriptors()["types"]
    assert set(kinds) == {"rule", "skill", "tool", "hook", "agent"}
    for definition in kinds.values():
        assert all(
            field["label"] and field["placeholder"] for field in definition["fields"]
        )
    event = next(field for field in kinds["hook"]["fields"] if field["key"] == "event")
    assert set(event["choices"]) == set().union(
        *(set(events) for events in HOOK_EVENT_MAP.values())
    )


def test_rule_clone_is_an_artifact_without_polluting_ordinary_instructions():
    body = "Complete rule.\n" * 5000 + "FINAL RULE CONTEXT"
    content = compose(
        "rule",
        {"instructions": body, "clone_description": "Use for complete reviews."},
        clone_as_skill=True,
    )
    assert content["body"] == body
    row = {"name": "sample", "content": content}
    rendered = editor.render_rule_clone(row)
    assert yaml.safe_load(rendered.split("---\n", 2)[1]) == {
        "name": "sample",
        "description": "Use for complete reviews.",
    }
    assert rendered.endswith("FINAL RULE CONTEXT")
    assert content["body"] == body


def test_legacy_rule_clones_are_verbatim_unless_managed_description_is_explicit():
    body = "---\nname: sample\ndescription: Legacy\ncustom: [false, 0]\n---\n\nComplete instructions.\n"
    assert (
        editor.render_rule_clone(
            {"name": "sample", "content": {"body": body, "metadata": {}}}
        )
        == body
    )
    rendered = editor.render_rule_clone(
        {
            "name": "sample",
            "content": {"body": body, "metadata": {"skill_description": "Updated"}},
        }
    )
    assert rendered.count("---\n") == 2
    assert yaml.safe_load(rendered.split("---\n", 2)[1])["custom"] == [False, 0]
    assert rendered.endswith("Complete instructions.\n")


def test_stdio_fields_preserve_argument_boundaries_empty_values_and_templates():
    from scripts.shared.agents import AGENT_TARGETS

    fields = {
        "transport": "stdio",
        "command": "${AGENT_SMITH_ROOT}/.venv/bin/python",
        "args": ["--name", "two words", ""],
        "env": [{"key": "TOKEN", "value": "${TOKEN}"}, {"key": "EMPTY", "value": ""}],
        "description": "Local tools",
    }
    content = compose("tool", fields)
    assert content["metadata"]["args"] == ["--name", "two words", ""]
    assert content["metadata"]["env"] == {"TOKEN": "${TOKEN}", "EMPTY": ""}
    for target in AGENT_TARGETS.values():
        published = target["mcp_transform"](content["metadata"])
        assert (
            published["args"] == fields["args"]
            and published["env"]["TOKEN"] == "${TOKEN}"
        )


@pytest.mark.parametrize(
    "url",
    ["https://example.com/mcp", "http://localhost:${PORT}/mcp", "${MCP_BASE}/mcp"],
)
def test_http_fields_support_existing_templates_without_expanding_secrets(url):
    result = compose(
        "tool",
        {
            "transport": "http",
            "url": url,
            "headers": [{"key": "Authorization", "value": "Bearer ${PRIVATE_TOKEN}"}],
            "oauth_client_id": "client-1",
        },
    )
    assert result["metadata"]["url"] == url
    assert result["metadata"]["headers"] == {"Authorization": "Bearer ${PRIVATE_TOKEN}"}
    assert result["metadata"]["oauth"]["clientId"] == "client-1"


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "ftp://example.com/mcp"},
        {"url": "relative/path"},
        {"headers": [{"key": "Bad\nHeader", "value": "PRIVATE VALUE"}]},
        {
            "headers": [
                {"key": "Duplicate", "value": "one"},
                {"key": "duplicate", "value": "two"},
            ]
        },
        {
            "env": [{"key": "BAD KEY", "value": "PRIVATE VALUE"}],
            "transport": "stdio",
            "command": "python",
        },
    ],
)
def test_tool_errors_identify_fields_without_echoing_secret_values(changes):
    with pytest.raises(ValueError, match="fields") as failure:
        compose(
            "tool", {"transport": "http", "url": "https://example.com/mcp", **changes}
        )
    assert "PRIVATE VALUE" not in str(failure.value)


def test_tool_unknown_metadata_and_oauth_siblings_survive_one_field_edit():
    original = {
        "url": "https://example.com/mcp",
        "oauth": {"clientId": "old", "custom": {"zero": 0, "false": False}},
        "custom": ["", None],
    }
    result = compose("tool", {"oauth_client_id": "new"}, metadata=original)
    assert result["metadata"] == {
        **original,
        "oauth": {**original["oauth"], "clientId": "new"},
    }


def test_switching_tool_transport_removes_only_the_inactive_managed_transport():
    result = compose(
        "tool",
        {"transport": "stdio", "command": "python"},
        metadata={
            "url": "https://example.com",
            "headers": {"X-Test": "keep-in-draft"},
            "custom": False,
        },
    )
    assert "url" not in result["metadata"] and "headers" not in result["metadata"]
    assert (
        result["metadata"]["command"] == "python"
        and result["metadata"]["custom"] is False
    )


def test_hook_settings_reuse_model_defaults_and_managed_permissions():
    from services.api.models.hook import compile_hook_settings

    content = compose(
        "hook",
        {
            "event": "pre_tool_use",
            "matcher": "Bash",
            "default_model": "haiku",
            "handlers": [{"type": "prompt", "prompt": "Review the complete command."}],
            "permissions": ["mcp__memory__memory_search"],
        },
    )
    settings = compile_hook_settings([{"name": "sample", "content": content}], "claude")
    assert settings.hooks["PreToolUse"][0]["hooks"][0]["model"] == "haiku"
    assert settings.allowed_tools == ["mcp__memory__memory_search"]


@pytest.mark.parametrize(
    "handler",
    [
        {"type": "command", "command": ""},
        {"type": "prompt", "prompt": ""},
        {"type": "agent", "prompt": "Valid", "timeout": -1},
        {"type": "command", "command": "python script.py", "model": "haiku"},
    ],
)
def test_invalid_hook_handler_fields_fail_before_storage(handler):
    with pytest.raises(ValueError, match="fields.handlers"):
        compose("hook", {"event": "pre_tool_use", "handlers": [handler]})


def test_agent_changes_preserve_legacy_list_representation_and_unknown_metadata(
    tmp_path, monkeypatch
):
    from scripts.shared import fs
    from scripts.shared.agents import AGENT_TARGETS

    metadata = {
        "description": "Reviews changes",
        "model": "old",
        "tools": "Read, Write",
        "custom": {"enabled": False, "limit": 0},
    }
    body = "All agent context.\n" * 8000 + "FINAL AGENT SENTINEL"
    result = compose("agent", {"model": "new"}, metadata=metadata, body=body)
    assert result["metadata"] == {**metadata, "name": "sample", "model": "new"}
    assert result["body"] == body
    monkeypatch.setitem(AGENT_TARGETS["claude"], "agents_dir", str(tmp_path))
    monkeypatch.setattr(
        "services.api.models.agent.collect_agents_from_db",
        lambda agent: {"sample": {**result, "scoped_rules": []}},
    )
    fs.sync_agents("claude", False)
    published = (tmp_path / "sample.md").read_text()
    assert "FINAL AGENT SENTINEL" in published
    header = yaml.safe_load(published.split("---\n", 2)[1])
    assert header["tools"] == "Read, Write" and header["custom"] == metadata["custom"]
    assert header["name"] == "sample"


def test_new_agent_has_native_name_and_inherits_tools_when_no_restriction_is_selected():
    content = editor.compose(
        "agent",
        "sample",
        fields={
            "description": "Review changes",
            "instructions": "Complete instructions.",
        },
        extensions={"metadata": {}},
    )
    assert content["metadata"]["name"] == "sample"
    assert "tools" not in content["metadata"]
    draft = editor.decode("agent", "sample", content)
    assert draft["fields"]["inherit_tools"] is True
    assert "name" not in draft["extensions"]["metadata"]


def test_existing_empty_tool_restriction_is_preserved_until_inheritance_is_explicit():
    metadata = {
        "name": "sample",
        "description": "Review changes",
        "tools": [],
        "custom": False,
    }
    original = {"body": "Complete instructions.", "metadata": metadata}
    draft = editor.decode("agent", "sample", original)
    assert draft["fields"]["inherit_tools"] is False
    unchanged = editor.compose(
        "agent",
        "sample",
        fields=draft["fields"],
        extensions=draft["extensions"],
        original_content=original,
        dirty_paths=[],
    )
    assert unchanged == original
    changed = editor.compose(
        "agent",
        "sample",
        fields={**draft["fields"], "inherit_tools": True},
        extensions=draft["extensions"],
        original_content=original,
        dirty_paths=["/fields/inherit_tools"],
    )
    assert "tools" not in changed["metadata"] and changed["metadata"]["custom"] is False


def test_agent_rename_assembles_the_native_header_name_once():
    original = {
        "body": "Complete instructions.",
        "metadata": {"name": "sample", "description": "Review changes", "custom": 0},
    }
    draft = editor.decode("agent", "sample", original)
    changed = editor.compose(
        "agent",
        "renamed",
        source_name="sample",
        fields=draft["fields"],
        extensions=draft["extensions"],
        original_content=original,
        dirty_paths=[],
    )
    assert changed["metadata"]["name"] == "renamed"
    assert changed["metadata"]["custom"] == 0


def test_changed_raw_agent_cannot_have_a_mismatched_native_name():
    with pytest.raises(ValueError, match="raw.name"):
        editor.compose_raw(
            "agent",
            "sample",
            "---\nname: another\ndescription: Review changes\n---\nComplete instructions.",
        )


def test_hook_permission_agent_error_identifies_the_actionable_field():
    with pytest.raises(ValueError, match=r"fields.permissions.*Claude"):
        compose(
            "hook",
            {
                "event": "pre_tool_use",
                "handlers": [{"type": "prompt", "prompt": "Review all context."}],
                "permissions": ["mcp__memory__memory_search"],
            },
            agents=["codex"],
        )


@pytest.mark.parametrize("kind", ["rule", "tool", "hook", "agent"])
def test_each_kind_roundtrips_untouched_raw_content_exactly(kind):
    metadata = (
        {"url": "https://example.com", "custom": [False, 0, ""]}
        if kind == "tool"
        else {"event": "pre_tool_use", "hooks": []}
        if kind == "hook"
        else {"description": "Description", "custom": {"empty": ""}}
    )
    original = {
        "body": "All original text.\r\n",
        "metadata": metadata,
        "custom_content": {"keep": True},
    }
    draft = editor.decode(kind, "sample", original)
    assert draft["capabilities"]["guided_supported"] is True
    assert (
        editor.compose(
            kind,
            "sample",
            fields=draft["fields"],
            extensions=draft["extensions"],
            original_content=original,
            dirty_paths=[],
        )
        == original
    )
    assert editor.compose_raw(kind, "sample", draft["raw"], original) == original


def test_raw_json_duplicate_keys_are_rejected_without_discarding_unknown_data():
    original = {
        "body": "Notes",
        "metadata": {"url": "https://example.com", "custom": 0},
    }
    with pytest.raises(ValueError, match="raw"):
        editor.compose_raw(
            "tool",
            "sample",
            '{"url":"https://one.example","url":"https://two.example"}',
            original,
        )
    updated = editor.compose_raw(
        "tool",
        "sample",
        json.dumps({**original["metadata"], "custom": False}),
        original,
    )
    assert updated["metadata"]["custom"] is False and updated["body"] == "Notes"


def test_all_kind_browser_fixtures_are_actual_native_codec_documents():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/harness_editor_types.json").read_text()
    )
    assert fixture["descriptors"] == editor.descriptors()
    for kind, case in fixture["cases"].items():
        for item_key, draft_key in (("item", "draft"), ("updated", "updated_draft")):
            item = case[item_key]
            assert editor.decode(kind, item["name"], item["content"]) == case[draft_key]
        created = editor.compose(
            kind,
            case["common"]["name"],
            fields=case["fields"],
            extensions=case["extensions"],
            clone_as_skill=case["common"]["clone_as_skill"],
            agents=case["common"]["agents"],
        )
        assert created == case["item"]["content"]
        defaults = {
            field["key"]: field.get("default", "")
            for field in fixture["descriptors"]["types"][kind]["fields"]
        }
        with_inactive_defaults = editor.compose(
            kind,
            case["common"]["name"],
            fields={**defaults, **case["fields"]},
            extensions=case["extensions"],
            clone_as_skill=case["common"]["clone_as_skill"],
            agents=case["common"]["agents"],
        )
        assert with_inactive_defaults == created
