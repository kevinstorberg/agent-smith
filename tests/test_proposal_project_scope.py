from __future__ import annotations

import pytest

from services.api.models.harness_config import list_configs, update_config
from services.api.models.shared.harness import get_item, get_item_by_id, upsert_item
from services.db import get_connection
from services.proposals.service import (
    persist_proposal,
    promote_proposal,
    stage_proposal,
)
from tests.conftest import clean_harness_rows


@pytest.fixture(autouse=True)
def clean_scope_fixtures():
    yield
    with get_connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM improvement_proposals WHERE target_name LIKE 'propscope_%'"
        )
    clean_harness_rows("propscope_%")


def create_global(kind: str, name: str) -> int:
    item_id = upsert_item(
        kind,
        name,
        {"body": "Global original body.", "metadata": {"origin": "global"}},
        agents=["claude"],
    )
    [config] = list_configs(item_id, kind)
    update_config(config["id"], device="global-device")
    return item_id


def proposal(
    kind: str, name: str, action: str, project: str | None = "project-fixture"
) -> dict:
    return {
        "target_kind": kind,
        "target_name": name,
        "action": action,
        "project": project,
        "title": "Improve isolated scope fixture",
        "rationale": "Verify exact project writes.",
        "body": "Complete proposed body.",
    }


@pytest.mark.parametrize("kind", ["rule", "skill", "hook"])
def test_project_update_does_not_select_an_inherited_global_target(kind):
    name = f"propscope_missing_{kind}"
    global_id = create_global(kind, name)
    before = get_item_by_id(kind, global_id)

    with pytest.raises(ValueError, match="does not exist"):
        stage_proposal(proposal(kind, name, "update"))

    assert get_item_by_id(kind, global_id) == before
    assert get_item(kind, name, project="project-fixture")["id"] == global_id


@pytest.mark.parametrize("kind", ["rule", "skill", "hook"])
def test_project_create_promotes_an_independent_override_without_modifying_global(kind):
    name = f"propscope_create_{kind}"
    global_id = create_global(kind, name)
    before = get_item_by_id(kind, global_id)

    staged = stage_proposal(proposal(kind, name, "create"))
    assert staged["project"] == "project-fixture"
    assert staged["target_id"] is None and staged["base_version"] is None
    assert staged["content"]["metadata"] == {}
    assert staged["seed"]["agents"] == []
    promoted = promote_proposal(persist_proposal(staged))

    project = get_item(kind, name, project="project-fixture")
    assert project["id"] == promoted["applied_ref"]["item_id"]
    assert project["project"] == "project-fixture" and project["version"] == 1
    assert project["content"] == {"body": "Complete proposed body.", "metadata": {}}
    [config] = list_configs(project["id"], kind)
    assert config["device"] == "*" and config["agents"] == []
    assert get_item_by_id(kind, global_id) == before
    assert get_item(kind, name)["id"] == global_id


@pytest.mark.parametrize("kind", ["rule", "skill", "hook"])
def test_project_update_binds_and_promotes_only_the_exact_project_identity(kind):
    name = f"propscope_update_{kind}"
    global_id = create_global(kind, name)
    project_id = upsert_item(
        kind,
        name,
        {"body": "Project original body.", "metadata": {"origin": "project"}},
        project="project-fixture",
        agents=["codex"],
    )
    before = get_item_by_id(kind, global_id)
    project_before = get_item_by_id(kind, project_id)

    staged = stage_proposal(proposal(kind, name, "update"))
    assert staged["project"] == "project-fixture"
    assert staged["target_id"] == project_id
    assert staged["base_version"] == project_before["version"]
    promoted = promote_proposal(persist_proposal(staged))

    project = get_item(kind, name, project="project-fixture")
    assert project["id"] == promoted["applied_ref"]["item_id"]
    assert project["version"] == project_before["version"] + 1
    assert project["content"] == {
        "body": "Complete proposed body.",
        "metadata": {"origin": "project"},
    }
    assert project["agents"] == ["codex"]
    assert get_item_by_id(kind, global_id) == before


@pytest.mark.parametrize("kind", ["rule", "skill", "hook"])
@pytest.mark.parametrize("project", [None, ""])
def test_unspecified_project_still_updates_the_global_identity(kind, project):
    name = f"propscope_global_{kind}"
    global_id = create_global(kind, name)
    upsert_item(
        kind,
        name,
        {"body": "Project original body.", "metadata": {}},
        project="project-fixture",
    )
    project_before = get_item(kind, name, project="project-fixture")

    staged = stage_proposal(proposal(kind, name, "update", project))
    assert staged["project"] is None
    assert staged["target_id"] == global_id
    promoted = promote_proposal(persist_proposal(staged))

    assert get_item(kind, name)["id"] == promoted["applied_ref"]["item_id"]
    assert get_item(kind, name, project="project-fixture") == project_before
