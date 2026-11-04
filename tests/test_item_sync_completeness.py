from __future__ import annotations

from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.shared import agents, fs
from services.api.models import harness_config
from services.api.models.shared import harness


def snapshot(root):
    return {
        str(path.relative_to(root)): (
            path.read_bytes() if path.is_file() else None,
            path.stat().st_mtime_ns,
            path.stat().st_ino,
        )
        for path in sorted(root.rglob("*"))
    }


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    global_targets = {}
    roots = {}
    for agent in ("claude", "codex"):
        root = tmp_path / ("global-" + agent)
        roots[agent] = root
        global_targets[agent] = {
            **agents.AGENT_TARGETS[agent],
            "rules_file": str(root / "RULES.md"),
            "rules_dir": str(root / "rules"),
            "skills_dir": str(root / "skills"),
        }
    monkeypatch.setattr(agents, "AGENT_TARGETS", global_targets)
    repos = [tmp_path / "selected-repo", tmp_path / "unrelated-repo"]
    for repo in repos:
        repo.mkdir()
    inventory = {"rule": [], "skill": []}
    identifiers = count(1)

    def add(kind, name, target="*", agent="claude", clone=False):
        row = {
            "id": next(identifiers),
            "name": name,
            "agents": [agent],
            "clone_as_skill": clone,
            "content": {"body": name + " original body\n", "metadata": {}},
            "configs": [
                {
                    "device": "*",
                    "repo": str(target),
                    "agents": [agent],
                    "enabled": True,
                    "exclude": False,
                }
            ],
        }
        inventory[kind].append(row)
        return row

    def full(kind):
        return list(inventory.get(kind, []))

    def get(kind, identifier):
        return next((row for row in full(kind) if row["id"] == identifier), None)

    monkeypatch.setattr(harness, "list_items_full", full)
    monkeypatch.setattr(harness, "get_item_by_id", get)
    monkeypatch.setattr(
        harness_config,
        "list_configs",
        lambda identifier, kind: get(kind, identifier)["configs"],
    )

    def publish():
        for agent in global_targets:
            fs.sync_rules(agent, False, "test-device")
            fs.sync_skills(agent, False, "test-device")

    def config(target, agent="claude"):
        return (
            global_targets[agent]
            if target == "*"
            else agents.repo_config(agent, str(target))
        )

    return SimpleNamespace(
        add=add,
        full=full,
        inventory=inventory,
        roots=roots,
        repos=repos,
        publish=publish,
        config=config,
    )


@pytest.mark.parametrize(
    "kind,clone", [("rule", False), ("skill", False), ("rule", True)]
)
@pytest.mark.parametrize("scope", ["global", "repository"])
def test_item_sync_complete_inventory_preserves_siblings_and_only_selected_destinations(
    deployment, kind, clone, scope
):
    selected_repo, other_repo = deployment.repos
    target = "*" if scope == "global" else selected_repo
    selected = deployment.add(kind, "selected", target, clone=clone)
    sibling = deployment.add(kind, "sibling", target, clone=clone)
    companion = deployment.add(
        "rule" if kind == "skill" else "skill",
        "companion",
        target,
        clone=kind == "skill",
    )
    unrelated = [
        deployment.add(kind, "other_repository", other_repo, clone=clone),
        deployment.add(kind, "other_agent", agent="codex", clone=clone),
    ]
    if scope == "repository":
        unrelated.append(deployment.add(kind, "global_only", clone=clone))
    deployment.publish()
    untouched_roots = [other_repo, deployment.roots["codex"]]
    if scope == "repository":
        untouched_roots.append(deployment.roots["claude"])
    untouched = {root: snapshot(root) for root in untouched_roots}
    cfg = deployment.config(target)
    sibling_file = (
        Path(cfg["rules_dir"]) / "sibling.md"
        if kind == "rule"
        else Path(cfg["skills_dir"]) / "sibling/SKILL.md"
    )
    sibling_before = (sibling_file.read_bytes(), sibling_file.stat().st_mtime_ns)
    selected["content"]["body"] = "Selected NEW body\n"
    for row in unrelated:
        row["content"]["body"] = (
            "Unrelated DB content changed and must not be published\n"
        )

    result = fs.sync_item(kind, selected["id"], "test-device")

    assert result["success"] is True
    assert sibling_file.exists(), "Per-item publication deleted its managed sibling"
    assert (
        sibling_file.read_bytes(),
        sibling_file.stat().st_mtime_ns,
    ) == sibling_before
    if kind == "rule":
        combined = Path(cfg["rules_file"]).read_text()
        assert selected["content"]["body"].strip() in combined
        assert sibling["content"]["body"].strip() in combined
        assert (Path(cfg["rules_dir"]) / "selected.md").read_text() == selected[
            "content"
        ]["body"]
    if kind == "skill" or clone:
        directory = Path(cfg["skills_dir"])
        assert (directory / "selected/SKILL.md").read_text() == selected["content"][
            "body"
        ]
        assert (directory / "sibling/SKILL.md").read_text() == sibling["content"][
            "body"
        ]
        assert (directory / "companion/SKILL.md").read_text() == companion["content"][
            "body"
        ]
    assert {root: snapshot(root) for root in untouched_roots} == untouched
    assert harness.list_items_full is deployment.full


@pytest.mark.parametrize("fail", [False, True])
def test_item_sync_never_replaces_global_collector_during_success_or_error(
    deployment, monkeypatch, fail
):
    selected = deployment.add("rule", "selected")
    deployment.add("rule", "sibling")
    publisher = fs.sync_rules
    observed = []

    def inspect(*args, **kwargs):
        observed.append(harness.list_items_full is deployment.full)
        if fail:
            raise OSError("Synthetic publisher failure")
        return publisher(*args, **kwargs)

    monkeypatch.setattr(fs, "sync_rules", inspect)
    if fail:
        with pytest.raises(OSError, match="Synthetic publisher failure"):
            fs.sync_item("rule", selected["id"])
    else:
        assert fs.sync_item("rule", selected["id"])["success"]
    assert observed == [True]
    assert harness.list_items_full is deployment.full
    assert len(harness.list_items_full("rule")) == 2


def test_item_sync_successive_kinds_cannot_leak_a_partial_inventory(deployment):
    rule = deployment.add("rule", "selected_rule", clone=True)
    deployment.add("rule", "other_rule", clone=True)
    skill = deployment.add("skill", "selected_skill")
    deployment.add("skill", "other_skill")
    for kind, selected in (("rule", rule), ("skill", skill), ("rule", rule)):
        assert fs.sync_item(kind, selected["id"])["success"]
        assert harness.list_items_full is deployment.full
        names = {
            path.name for path in (deployment.roots["claude"] / "skills").iterdir()
        }
        assert names == {"selected_rule", "other_rule", "selected_skill", "other_skill"}


@pytest.mark.parametrize(
    "kind,clone", [("rule", False), ("skill", False), ("rule", True)]
)
def test_item_sync_with_no_selected_destination_does_not_publish_another_inventory(
    deployment, kind, clone
):
    selected = deployment.add(kind, "selected", clone=clone)
    sibling = deployment.add(kind, "sibling", clone=clone)
    deployment.publish()
    before = snapshot(deployment.roots["claude"])
    selected["configs"][0]["enabled"] = False
    sibling["content"]["body"] = (
        "Changed source must not cause an unrelated publication\n"
    )
    assert fs.sync_item(kind, selected["id"])["success"]
    assert snapshot(deployment.roots["claude"]) == before


@pytest.mark.parametrize(
    "publisher,kind", [(fs.sync_rules, "rule"), (fs.sync_skills, "skill")]
)
def test_full_sync_keeps_default_all_destination_behavior(deployment, publisher, kind):
    global_row = deployment.add(kind, "global_item")
    repo_row = deployment.add(kind, "repo_item", deployment.repos[0])
    publisher("claude", False, "test-device")
    global_cfg, repo_cfg = (
        deployment.config("*"),
        deployment.config(deployment.repos[0]),
    )
    if kind == "rule":
        assert "global_item original body" in Path(global_cfg["rules_file"]).read_text()
        assert "repo_item original body" in Path(repo_cfg["rules_file"]).read_text()
    else:
        assert (
            Path(global_cfg["skills_dir"]) / "global_item/SKILL.md"
        ).read_text() == global_row["content"]["body"]
        assert (
            Path(repo_cfg["skills_dir"]) / "repo_item/SKILL.md"
        ).read_text() == repo_row["content"]["body"]
