from __future__ import annotations

from pathlib import Path

from scripts.shared.file_ownership import check_publication, publish_files
from scripts.shared.path_safety import contained_path


def compose_strings(items: list[tuple[str, str]], transform=None) -> str:
    parts: list[str] = []
    for name, raw in items:
        raw = raw.rstrip()
        text = transform(raw, name) if transform else raw
        parts.append(text)
    return "\n\n".join(parts) + "\n"


def extract_brief(content: str, rules_path: Path) -> str:
    marker = "* **Your Process:**"
    if marker not in content:
        return content
    before = content.split(marker)[0].rstrip()
    return f"{before}\n* **Your Process:** See `{rules_path}`\n"


def atomic_write(path: Path | str, content: str) -> tuple[bool, str]:
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False, f"unchanged: {path}"

    path.write_text(content, encoding="utf-8")
    return True, f"updated:   {path}"


def _sync_rules_to_target(
    items: list[tuple[str, str]],
    cfg: dict,
    dry_run: bool,
    *,
    owner: str = "agent-smith",
) -> None:
    rules_file = Path(cfg["rules_file"]).expanduser()
    rules_dir = Path(cfg["rules_dir"]).expanduser() if "rules_dir" in cfg else None

    if rules_dir:

        def transform(text, name):
            return extract_brief(text, rules_dir / f"{name}.md")
    else:
        transform = None

    content = compose_strings(items, transform=transform)

    check_publication(
        rules_file.parent, f"{owner}:rules-file", {rules_file.name: content}
    )
    if rules_dir:
        check_publication(
            rules_dir, f"{owner}:rules", {f"{name}.md": body for name, body in items}
        )
    publish_files(
        rules_file.parent,
        f"{owner}:rules-file",
        {rules_file.name: content},
        dry_run=dry_run,
        write=atomic_write,
    )
    if rules_dir:
        _sync_rules_dir(items, rules_dir, dry_run, owner=owner)


def _resolve_and_partition(
    item_type: str,
    agent: str,
    device_name: str,
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Resolve sync targets for all items and partition into global vs per-repo.

    Fetches all items regardless of legacy agent/enabled columns — config rows
    are the sole authority for sync decisions.
    """
    from services.api.models.shared.harness import list_items_full
    from services.api.models.harness_config import list_configs
    from services.api.models.shared.sync import resolve_sync_targets

    rows = list_items_full(item_type)
    global_items: list[dict] = []
    repo_items: dict[str, list[dict]] = {}

    for row in rows:
        configs = list_configs(row["id"], item_type)
        targets = resolve_sync_targets(
            {**row, "configs": configs}, agent=agent, device_name=device_name
        )
        for target in targets:
            if target == "*":
                global_items.append(row)
            else:
                repo_items.setdefault(target, []).append(row)

    return global_items, repo_items


def _sync_to_repo_targets(
    repo_rows: dict[str, list[dict]],
    agent: str,
    target_key: str,
    sync_fn,
    dry_run: bool,
) -> None:
    from scripts.shared.agents import repo_config

    for repo_path, rows in repo_rows.items():
        if not Path(repo_path).is_dir():
            print(f"  warning: repo path does not exist, skipping: {repo_path}")
            continue
        rcfg = repo_config(agent, repo_path)
        if rcfg.get(target_key):
            sync_fn(rows, rcfg, dry_run)


def _target_selected(target: str, destinations: set[str] | None) -> bool:
    return destinations is None or target in destinations


def sync_rules(
    agent: str,
    dry_run: bool,
    device_name: str = "",
    *,
    destinations: set[str] | None = None,
) -> None:
    from scripts.shared.agents import AGENT_TARGETS

    cfg = AGENT_TARGETS[agent]
    global_rows, repo_rows = _resolve_and_partition("rule", agent, device_name)

    global_items = [(r["name"], r["content"]["body"]) for r in global_rows]
    if _target_selected("*", destinations):
        _sync_rules_to_target(global_items, cfg, dry_run, owner=agent)

    def _repo_sync(rows, rcfg, dr):
        items = [(r["name"], r["content"]["body"]) for r in rows]
        _sync_rules_to_target(items, rcfg, dr, owner=agent)

    selected_repos = {
        repo: rows
        for repo, rows in repo_rows.items()
        if _target_selected(repo, destinations)
    }
    _sync_to_repo_targets(selected_repos, agent, "rules_file", _repo_sync, dry_run)


def _sync_rules_dir(
    items: list[tuple[str, str]],
    dest_dir: Path,
    dry_run: bool,
    *,
    owner: str = "agent-smith",
) -> None:
    publish_files(
        dest_dir,
        f"{owner}:rules",
        {f"{name}.md": body for name, body in items},
        dry_run=dry_run,
        write=atomic_write,
    )


def _skill_outputs(
    skills: dict[str, dict], dest_dir: Path
) -> dict[str, list[tuple[Path, str]]]:
    if not isinstance(skills, dict):
        raise ValueError("skills must be an object")
    outputs = {}
    for name, data in skills.items():
        if not isinstance(name, str) or "/" in name:
            raise ValueError("skill name must be a single path component")
        dest_skill = contained_path(dest_dir, name)
        if not isinstance(data, dict) or not isinstance(data.get("skill_md"), str):
            raise ValueError(f"skill {name!r} must provide string skill_md content")
        files = data.get("files", {})
        if not isinstance(files, dict):
            raise ValueError(f"skill {name!r} files must be an object")
        rendered = [(contained_path(dest_skill, "SKILL.md"), data["skill_md"])]
        for relative, content in files.items():
            destination = contained_path(dest_skill, relative)
            if not isinstance(content, str):
                raise ValueError(f"skill {name!r} files must contain string content")
            rendered.append((destination, content))
        outputs[name] = rendered
    return outputs


def _sync_skills_to_target(
    skills: dict[str, dict],
    dest_dir: Path,
    dry_run: bool,
    *,
    owner: str = "agent-smith",
) -> None:
    outputs = _skill_outputs(skills, dest_dir)
    root = dest_dir.expanduser().resolve()
    rendered = {
        str(destination.relative_to(root)): content
        for files in outputs.values()
        for destination, content in files
    }
    publish_files(
        root, f"{owner}:skills", rendered, dry_run=dry_run, write=atomic_write
    )


def _collect_skill_clones(
    agent: str,
    device_name: str,
) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
    from services.harness.editor_codecs import render_rule_clone

    global_rows, repo_rows = _resolve_and_partition("rule", agent, device_name)

    def to_skills(rows: list[dict]) -> dict[str, dict]:
        return {
            r["name"]: {"skill_md": render_rule_clone(r), "files": {}}
            for r in rows
            if r.get("clone_as_skill")
        }

    global_clones = to_skills(global_rows)
    repo_clones = {repo: to_skills(rows) for repo, rows in repo_rows.items()}
    return global_clones, repo_clones


def sync_skills(
    agent: str,
    dry_run: bool,
    device_name: str = "",
    *,
    destinations: set[str] | None = None,
) -> None:
    from scripts.shared.agents import AGENT_TARGETS
    from services.api.models.shared.harness import content_metadata

    cfg = AGENT_TARGETS[agent]
    global_rows, repo_rows = _resolve_and_partition("skill", agent, device_name)
    global_clones, repo_clones = _collect_skill_clones(agent, device_name)

    def rows_to_skills(rows: list[dict]) -> dict[str, dict]:
        result = {}
        for r in rows:
            meta = content_metadata(r)
            result[r["name"]] = {
                "skill_md": r["content"]["body"],
                "files": meta.get("files", {}),
            }
        return result

    global_skills = {**global_clones, **rows_to_skills(global_rows)}
    if _target_selected("*", destinations):
        _sync_skills_to_target(
            global_skills, Path(cfg["skills_dir"]).expanduser(), dry_run, owner=agent
        )

    from scripts.shared.agents import repo_config as _repo_config

    all_repo_paths = set(repo_rows) | set(repo_clones)
    for repo_path in all_repo_paths:
        if not _target_selected(repo_path, destinations):
            continue
        if not Path(repo_path).is_dir():
            print(f"  warning: repo path does not exist, skipping: {repo_path}")
            continue
        rcfg = _repo_config(agent, repo_path)
        if not rcfg.get("skills_dir"):
            continue
        clones = repo_clones.get(repo_path, {})
        real = rows_to_skills(repo_rows.get(repo_path, []))
        _sync_skills_to_target(
            {**clones, **real}, Path(rcfg["skills_dir"]), dry_run, owner=agent
        )


def _compose_agent_file(
    body: str, metadata: dict, scoped_rules: list | None = None
) -> str:
    from services.harness.frontmatter import compose_agent_file

    return compose_agent_file(body, metadata, scoped_rules)


def sync_agents(agent: str, dry_run: bool, device_name: str = "") -> None:
    from scripts.shared.agents import AGENT_TARGETS
    from services.api.models.agent import collect_agents_from_db

    cfg = AGENT_TARGETS[agent]
    agents_dir = cfg.get("agents_dir")
    if not agents_dir:
        return

    dest_dir = Path(agents_dir).expanduser()
    agent_defs = collect_agents_from_db(agent)

    outputs = {}
    for name, data in sorted(agent_defs.items()):
        filename = f"{name}.md"
        outputs[filename] = _compose_agent_file(
            data["body"],
            data["metadata"],
            data.get("scoped_rules"),
        )
    publish_files(
        dest_dir, f"{agent}:agents", outputs, dry_run=dry_run, write=atomic_write
    )


def sync_item(
    item_type: str, item_id: int, device_name: str = "", *, dry_run: bool = False
) -> dict:
    from services.api.models.shared.harness import get_item_by_id, _table
    from services.api.models.shared.sync import resolve_sync_targets
    from scripts.shared.agents import AGENT_TARGETS
    from scripts.shared.mcp_utils import sync_mcp
    from scripts.shared.hook_utils import sync_hooks

    _table(item_type)
    if type(dry_run) is not bool:
        raise ValueError("dry_run must be a boolean")
    item = get_item_by_id(item_type, item_id)

    if not item:
        return {
            "success": False,
            "item_name": None,
            "agents_synced": [],
            "message": f"{item_type} with id {item_id} not found",
        }

    agents_to_sync = []
    item_agents = item.get("agents", [])

    if item_agents:
        agents_to_sync = [a for a in item_agents if a in AGENT_TARGETS]
    else:
        for agent in AGENT_TARGETS:
            targets = resolve_sync_targets(item, agent=agent, device_name=device_name)
            if targets:
                agents_to_sync.append(agent)

    if not agents_to_sync:
        return {
            "success": True,
            "item_name": item["name"],
            "agents_synced": [],
            "message": "No agents to sync",
        }

    def selected_destinations(agent: str) -> set[str]:
        return set(resolve_sync_targets(item, agent=agent, device_name=device_name))

    withheld: list[str] = []
    sync_dispatch = {
        "rule": lambda a: sync_rules(
            a, dry_run, device_name, destinations=selected_destinations(a)
        ),
        "skill": lambda a: sync_skills(
            a, dry_run, device_name, destinations=selected_destinations(a)
        ),
        "tool": lambda a: withheld.extend(sync_mcp(a, dry_run)),
        "hook": lambda a: sync_hooks(a, dry_run),
        "agent": lambda a: sync_agents(a, dry_run, device_name),
    }

    for agent in agents_to_sync:
        print(f"[{agent}/{item_type}]")
        sync_dispatch[item_type](agent)

        if item_type == "rule" and item.get("clone_as_skill"):
            print(f"[{agent}/skills (clone)]")
            sync_skills(
                agent, dry_run, device_name, destinations=selected_destinations(agent)
            )

    if withheld:
        return {
            "success": False,
            "item_name": item["name"],
            "agents_synced": agents_to_sync,
            "message": "; ".join(withheld),
        }
    verb = "Would sync" if dry_run else "Synced"
    return {
        "success": True,
        "item_name": item["name"],
        "agents_synced": agents_to_sync,
        "message": f"{verb} to {len(agents_to_sync)} agent(s): {', '.join(agents_to_sync)}",
    }
