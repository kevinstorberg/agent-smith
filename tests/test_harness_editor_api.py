from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.models.harness_config import create_config, list_configs
from services.api.models.shared.harness import get_item_by_id, get_version_history
from services.api.routers import harness_router
from tests.conftest import harness_cleanup

_clean = harness_cleanup("editor_%")
app = FastAPI()
app.include_router(harness_router, prefix="/api/harness")
client = TestClient(app, raise_server_exceptions=False)


def payload(name="editor_skill", **changes):
    result = {
        "common": {
            "name": name,
            "project": "editor-project",
            "agents": ["claude"],
            "sort_key": 5,
            "device": "test-device",
            "repo": "/example/repo",
        },
        "mode": "guided",
        "fields": {
            "description": "Use during reviews",
            "instructions": "Complete instructions.",
            "files": [
                {"path": "references/check.md", "content": "Complete checklist."}
            ],
        },
        "extensions": {
            "frontmatter": {"custom": {"keep": [False, None, 0]}},
            "metadata": {"custom": "keep"},
        },
    }
    result.update(changes)
    return result


def created(name="editor_skill"):
    response = client.post("/api/harness/editor/skill", json=payload(name))
    assert response.status_code == 201, response.text
    return response.json()


def update_payload(item, **changes):
    request = payload(item["name"])
    request.update(
        expected_version=item["version"],
        expected_updated_at=item["updated_at"],
        dirty_paths=[],
    )
    request.update(changes)
    return request


def test_editor_descriptors_and_create_assemble_content_and_initial_scope_atomically():
    response = client.get("/api/harness/editor/descriptors")
    assert response.status_code == 200
    item = created()
    assert item["version"] == 1
    assert "name: editor_skill\n" in item["content"]["body"]
    assert item["content"]["body"].endswith("Complete instructions.")
    assert item["content"]["metadata"]["custom"] == "keep"
    assert [(row["device"], row["repo"], row["agents"]) for row in item["configs"]] == [
        ("test-device", "/example/repo", ["claude"])
    ]
    decoded = client.get(f"/api/harness/editor/skill/{item['id']}").json()
    assert decoded["item"]["id"] == item["id"]
    assert decoded["draft"]["fields"]["description"] == "Use during reviews"
    assert decoded["draft"]["extensions"]["frontmatter"]["custom"] == {
        "keep": [False, None, 0]
    }


def test_no_change_save_keeps_source_id_version_and_exact_content():
    item = created()
    response = client.put(
        f"/api/harness/editor/skill/{item['id']}", json=update_payload(item)
    )
    assert response.status_code == 200, response.text
    assert response.json() == item
    assert len(get_version_history("skill", item["name"], item["project"])) == 1


def test_editor_update_preserves_live_configs_unknown_fields_and_common_metadata():
    item = created()
    create_config(
        item["id"],
        "skill",
        device="other-device",
        repo="/other/repo",
        agents=["codex"],
        subagents=["*"],
        enabled=False,
        exclude=True,
    )
    request = update_payload(item)
    request["fields"]["instructions"] = "Updated instructions, all preserved."
    request["dirty_paths"] = ["/fields/instructions"]
    request["common"].update(
        name="editor_renamed", project="editor-new-project", enabled=False
    )
    response = client.put(f"/api/harness/editor/skill/{item['id']}", json=request)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["id"] != item["id"] and updated["version"] == 2
    assert (
        updated["name"] == "editor_renamed"
        and updated["project"] == "editor-new-project"
        and updated["enabled"] is False
    )
    assert "name: editor_renamed\n" in updated["content"]["body"]
    assert updated["content"]["metadata"]["custom"] == "keep"
    expected = [
        {
            key: value
            for key, value in row.items()
            if key not in {"id", "item_id", "created_at", "updated_at"}
        }
        for row in list_configs(item["id"], "skill")
    ]
    actual = [
        {
            key: value
            for key, value in row.items()
            if key not in {"id", "item_id", "created_at", "updated_at"}
        }
        for row in list_configs(updated["id"], "skill")
    ]
    assert actual == expected


def test_stale_timestamp_and_superseded_id_are_rejected_without_new_versions():
    item = created()
    request = update_payload(item)
    request["expected_updated_at"] = "2000-01-01T00:00:00.000001Z"
    assert (
        client.put(f"/api/harness/editor/skill/{item['id']}", json=request).status_code
        == 409
    )
    request = update_payload(item, dirty_paths=["/fields/instructions"])
    request["fields"]["instructions"] = "Changed once."
    assert (
        client.put(f"/api/harness/editor/skill/{item['id']}", json=request).status_code
        == 200
    )
    assert (
        client.put(f"/api/harness/editor/skill/{item['id']}", json=request).status_code
        == 409
    )
    assert len(get_version_history("skill", item["name"], item["project"])) == 2


def test_occupied_rename_destination_is_rejected_without_touching_either_item():
    item = created()
    other = created("editor_other")
    request = update_payload(item)
    request["common"]["name"] = other["name"]
    assert (
        client.put(f"/api/harness/editor/skill/{item['id']}", json=request).status_code
        == 409
    )
    assert get_item_by_id("skill", item["id"])["content"] == item["content"]
    assert get_item_by_id("skill", other["id"])["content"] == other["content"]


def test_failed_config_inheritance_rolls_back_content_and_identity_together(
    monkeypatch,
):
    from services.api.models.shared import harness

    item = created()
    request = update_payload(item, dirty_paths=["/fields/instructions"])
    request["fields"]["instructions"] = "Never committed."
    request["common"]["name"] = "editor_failed_rename"

    def fail(*args):
        raise RuntimeError("Injected copy failure")

    monkeypatch.setattr(harness, "_copy_configs", fail)
    assert (
        client.put(f"/api/harness/editor/skill/{item['id']}", json=request).status_code
        == 500
    )
    assert get_item_by_id("skill", item["id"])["content"] == item["content"]
    assert get_version_history("skill", "editor_failed_rename", "editor-project") == []


def test_concurrent_editor_saves_accept_exactly_one_snapshot():
    item = created()
    requests = [
        update_payload(item, dirty_paths=["/fields/instructions"]) for _ in range(2)
    ]
    for index, request in enumerate(requests):
        request["fields"]["instructions"] = f"Concurrent draft {index}."
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(
            pool.map(
                lambda request: (
                    client.put(
                        f"/api/harness/editor/skill/{item['id']}", json=request
                    ).status_code
                ),
                requests,
            )
        )
    assert sorted(statuses) == [200, 409]
    assert len(get_version_history("skill", item["name"], item["project"])) == 2


def test_validation_errors_never_echo_raw_prompts_or_secret_values():
    request = payload()
    request["fields"] = "PRIVATE CONTEXT MUST NOT APPEAR IN ERRORS"
    response = client.post("/api/harness/editor/skill", json=request)
    assert response.status_code == 422
    assert "PRIVATE CONTEXT" not in response.text
    assert "fields" in response.text


def test_raw_skill_preview_and_save_reopen_preserve_unknown_fields_and_supporting_files():
    item = created()
    request = update_payload(
        item,
        mode="raw",
        raw=item["content"]["body"].replace(
            "Complete instructions.", "Raw updated instructions."
        ),
    )
    request["original_content"] = item["content"]
    preview = client.post("/api/harness/editor/skill/preview", json=request)
    assert preview.status_code == 200, preview.text
    assert (
        preview.json()["draft"]["fields"]["instructions"] == "Raw updated instructions."
    )
    response = client.put(f"/api/harness/editor/skill/{item['id']}", json=request)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["content"]["body"] == request["raw"]
    assert updated["content"]["metadata"] == item["content"]["metadata"]
    reread = client.get(f"/api/harness/editor/skill/{updated['id']}")
    assert reread.json()["draft"]["extensions"]["frontmatter"]["custom"] == {
        "keep": [False, None, 0]
    }


def test_invalid_raw_skill_cannot_commit_or_discard_the_original_document():
    item = created()
    request = update_payload(
        item,
        mode="raw",
        raw="---\nname: [invalid\n---\nRaw draft retained client-side.",
    )
    response = client.put(f"/api/harness/editor/skill/{item['id']}", json=request)
    assert response.status_code == 422
    assert get_item_by_id("skill", item["id"])["content"] == item["content"]


def test_incomplete_guided_preview_is_inspectable_but_cannot_be_saved_through_raw():
    request = payload()
    request["fields"].update(description="", instructions="")
    preview = client.post("/api/harness/editor/skill/preview", json=request)
    assert preview.status_code == 200, preview.text
    request.update(mode="raw", raw=preview.json()["draft"]["raw"])
    assert client.post("/api/harness/editor/skill", json=request).status_code == 422


def test_guided_file_changes_survive_a_subsequent_raw_save():
    item = created()
    request = update_payload(
        item, mode="raw", raw=item["content"]["body"], dirty_paths=["/fields/files"]
    )
    request["fields"]["files"].append(
        {"path": "references/new.md", "content": "Retain new reference."}
    )
    response = client.put(f"/api/harness/editor/skill/{item['id']}", json=request)
    assert response.status_code == 200, response.text
    assert (
        response.json()["content"]["metadata"]["files"]["references/new.md"]
        == "Retain new reference."
    )


KINDS = {
    "rule": (
        {
            "instructions": "Complete rule instructions.",
            "clone_description": "Use for complete reviews.",
        },
        "instructions",
        "Updated complete rule.",
        {"metadata": {"custom": [False, 0, ""]}},
    ),
    "tool": (
        {
            "transport": "stdio",
            "command": "python",
            "args": ["--name", "two words", ""],
            "env": [{"key": "TOKEN", "value": "${TOKEN}"}],
            "description": "Original",
        },
        "description",
        "Updated description",
        {"metadata": {"custom": [False, 0, ""]}, "oauth": {}},
    ),
    "hook": (
        {
            "event": "pre_tool_use",
            "matcher": "Bash",
            "handlers": [
                {
                    "type": "prompt",
                    "prompt": "Review complete context.",
                    "settings": {"custom": False},
                }
            ],
            "default_model": "haiku",
            "permissions": ["mcp__memory__memory_search"],
        },
        "matcher",
        "Read|Write",
        {"metadata": {"custom": [False, 0, ""]}},
    ),
    "agent": (
        {
            "description": "Reviews complete changes",
            "instructions": "Complete agent context.",
            "model": "sonnet",
            "tools": ["Read", "Write"],
            "skills": ["review_changes"],
        },
        "instructions",
        "Updated complete agent context.",
        {"metadata": {"custom": [False, 0, ""]}},
    ),
}


@pytest.mark.parametrize("kind", KINDS)
def test_every_kind_uses_backend_assembly_atomic_save_and_reopen(kind):
    fields, changed_field, updated_value, extensions = KINDS[kind]
    request = payload("editor_" + kind, fields=fields, extensions=extensions)
    if kind == "rule":
        request["common"]["clone_as_skill"] = True
    response = client.post(f"/api/harness/editor/{kind}", json=request)
    assert response.status_code == 201, response.text
    item = response.json()
    decoded = client.get(f"/api/harness/editor/{kind}/{item['id']}").json()["draft"]
    assert decoded["capabilities"]["guided_supported"] is True
    assert item["content"]["metadata"]["custom"] == [False, 0, ""]
    request.update(
        fields={**decoded["fields"], changed_field: updated_value},
        extensions=decoded["extensions"],
        dirty_paths=["/fields/" + changed_field],
        expected_version=item["version"],
        expected_updated_at=item["updated_at"],
    )
    response = client.put(f"/api/harness/editor/{kind}/{item['id']}", json=request)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["version"] == 2 and updated["id"] != item["id"]
    reopened = client.get(f"/api/harness/editor/{kind}/{updated['id']}").json()["draft"]
    assert reopened["fields"][changed_field] == updated_value
    assert updated["content"]["metadata"]["custom"] == [False, 0, ""]
    if kind == "rule":
        from services.api.models.shared.harness import get_item

        assert updated["clone_as_skill"] is True
        assert get_item("skill", updated["name"], updated["project"]) is None


def test_rule_content_and_clone_override_are_committed_as_one_new_version():
    fields, _, _, extensions = KINDS["rule"]
    request = payload("editor_clone", fields=fields, extensions=extensions)
    request["common"]["clone_as_skill"] = True
    item = client.post("/api/harness/editor/rule", json=request).json()
    request["common"]["clone_as_skill"] = False
    request["fields"] = {**fields, "instructions": "Updated content and flag together."}
    request.update(
        dirty_paths=["/fields/instructions"],
        expected_version=item["version"],
        expected_updated_at=item["updated_at"],
    )
    response = client.put(f"/api/harness/editor/rule/{item['id']}", json=request)
    assert response.status_code == 200, response.text
    assert (
        response.json()["version"] == 2 and response.json()["clone_as_skill"] is False
    )
    assert get_item_by_id("rule", item["id"])["clone_as_skill"] is True


@pytest.mark.parametrize("mode", ["guided", "raw"])
def test_enabling_rule_clone_without_description_fails_before_mutating_the_row(mode):
    request = payload(
        "editor_enable_clone",
        fields={"instructions": "Ordinary rule."},
        extensions={"metadata": {}},
    )
    item = client.post("/api/harness/editor/rule", json=request).json()
    request["common"]["clone_as_skill"] = True
    request.update(
        mode=mode,
        raw=item["content"]["body"],
        dirty_paths=[],
        expected_version=item["version"],
        expected_updated_at=item["updated_at"],
    )
    response = client.put(f"/api/harness/editor/rule/{item['id']}", json=request)
    assert response.status_code == 422, response.text
    assert "clone_description" in response.text
    assert client.get(f"/api/harness/editor/rule/{item['id']}").json()["item"] == item


@pytest.mark.parametrize("mode", ["guided", "raw"])
def test_enabling_rule_clone_assembles_a_valid_derived_description_atomically(mode):
    from services.harness.editor import render_rule_clone

    body = "---\nname: editor_enable_clone\ndescription: Use when reviewing changes.\ncustom: false\n---\nComplete instructions."
    request = payload(
        "editor_enable_clone",
        fields={"instructions": body},
        extensions={"metadata": {}},
    )
    item = client.post("/api/harness/editor/rule", json=request).json()
    request["common"]["clone_as_skill"] = True
    request.update(
        mode=mode,
        raw=body,
        dirty_paths=[],
        expected_version=item["version"],
        expected_updated_at=item["updated_at"],
    )
    response = client.put(f"/api/harness/editor/rule/{item['id']}", json=request)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["clone_as_skill"] is True
    assert saved["content"]["body"] == body
    assert (
        saved["content"]["metadata"]["skill_description"]
        == "Use when reviewing changes."
    )
    assert render_rule_clone(saved).count("name: editor_enable_clone") == 1
    assert saved["version"] == 2
    assert get_item_by_id("rule", item["id"])["clone_as_skill"] is False


def test_existing_legacy_rule_clone_no_change_save_preserves_exact_verbatim_source():
    from services.api.models.shared.harness import create_item
    from services.api.models.rule import RuleModel

    item_id = create_item(
        "rule",
        "editor_legacy_clone",
        {"body": "Legacy verbatim rule.\r\n", "metadata": {"custom": False}},
        agents=["claude"],
    )
    RuleModel.dynamic_update(item_id, {"clone_as_skill": True})
    item = client.get(f"/api/harness/editor/rule/{item_id}").json()["item"]
    request = payload(item["name"], fields={}, extensions={})
    request["common"].update(
        project=item["project"], sort_key=item["sort_key"], clone_as_skill=True
    )
    request.update(
        expected_version=item["version"],
        expected_updated_at=item["updated_at"],
        dirty_paths=[],
    )
    response = client.put(f"/api/harness/editor/rule/{item['id']}", json=request)
    assert response.status_code == 200, response.text
    assert response.json() == item


@pytest.mark.parametrize("mode", ["guided", "raw"])
@pytest.mark.parametrize(
    "body", ["", "---\nname: editor_empty_clone\ndescription: Review changes\n---\n"]
)
def test_enabling_rule_clone_requires_nonblank_unwrapped_instructions(mode, body):
    from services.api.models.shared.harness import create_item

    item_id = create_item(
        "rule",
        "editor_empty_clone",
        {"body": body, "metadata": {"skill_description": "Review changes"}},
        agents=["claude"],
    )
    item = client.get(f"/api/harness/editor/rule/{item_id}").json()["item"]
    request = payload(item["name"], fields={}, extensions={})
    request["common"].update(
        project=item["project"], sort_key=item["sort_key"], clone_as_skill=True
    )
    request.update(
        mode=mode,
        raw=body,
        dirty_paths=[],
        expected_version=item["version"],
        expected_updated_at=item["updated_at"],
    )
    response = client.put(f"/api/harness/editor/rule/{item_id}", json=request)
    assert response.status_code == 422, response.text
    assert "fields.instructions" in response.text
    assert client.get(f"/api/harness/editor/rule/{item_id}").json()["item"] == item


@pytest.mark.parametrize("endpoint", ["", "/preview"])
@pytest.mark.parametrize("handlers", [7, {"type": "command"}, ["not-a-handler"]])
def test_malformed_raw_hook_handlers_are_actionable_422_not_server_errors(
    endpoint, handlers
):
    import json

    request = payload(
        "editor_invalid_hook",
        mode="raw",
        fields={},
        extensions={"metadata": {}},
        raw=json.dumps({"event": "pre_tool_use", "hooks": handlers}),
    )
    response = client.post("/api/harness/editor/hook" + endpoint, json=request)
    assert response.status_code == 422, response.text
    assert "fields.handlers" in response.text
    assert not get_version_history("hook", "editor_invalid_hook", "editor-project")


def test_timestamp_cas_distinguishes_updates_within_the_same_millisecond():
    from services.db import get_connection

    item = created()
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "UPDATE harness_skills SET updated_at='2026-11-05T12:00:00.123456Z' WHERE id=%s",
            (item["id"],),
        )
    item = client.get(f"/api/harness/editor/skill/{item['id']}").json()["item"]
    request = update_payload(item)
    request["expected_updated_at"] = "2026-11-05T12:00:00.123000Z"
    assert (
        client.put(f"/api/harness/editor/skill/{item['id']}", json=request).status_code
        == 409
    )
    request["expected_updated_at"] = "2026-11-05T12:00:00.123456Z"
    assert (
        client.put(f"/api/harness/editor/skill/{item['id']}", json=request).status_code
        == 200
    )


def test_new_editor_rejects_final_name_newline_without_changing_legacy_validation():
    response = client.post("/api/harness/editor/skill", json=payload("editor_name\n"))
    assert response.status_code == 422


def test_container_alias_document_roundtrips_raw_without_an_expanded_api_response():
    body = "---\nname: editor_alias\ndescription: Trigger\nbase: &base [one, two]\n"
    for index in range(8):
        previous = "base" if index == 0 else f"level{index - 1}"
        body += f"level{index}: &level{index} [*{previous}, *{previous}]\n"
    body += "---\nComplete instructions."
    response = client.post(
        "/api/harness/editor/skill", json=payload("editor_alias", mode="raw", raw=body)
    )
    assert response.status_code == 201, response.text
    item = response.json()
    decoded = client.get(f"/api/harness/editor/skill/{item['id']}")
    assert decoded.status_code == 200
    draft = decoded.json()["draft"]
    assert draft["capabilities"]["guided_supported"] is False
    assert "aliases" in draft["diagnostics"][0]["message"]
    assert draft["raw"] == body and draft["extensions"] == {}
    assert len(decoded.content) < 5_000
