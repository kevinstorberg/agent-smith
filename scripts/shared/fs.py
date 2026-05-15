from __future__ import annotations

import shutil
from pathlib import Path


def _remove_stale(dest_dir: Path, keep: set[str], *, match_dirs: bool = False) -> None:
    iterator = dest_dir.iterdir() if match_dirs else dest_dir.glob("*.md")
    for stale in iterator:
        if match_dirs and not stale.is_dir():
            continue
        if stale.name not in keep:
            shutil.rmtree(stale) if stale.is_dir() else stale.unlink()
            print(f"  removed:   {stale}")


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


def _sync_rules_to_target(items: list[tuple[str, str]], cfg: dict, dry_run: bool) -> None:
    rules_file = Path(cfg["rules_file"]).expanduser()
    rules_dir = Path(cfg["rules_dir"]).expanduser() if "rules_dir" in cfg else None

    if rules_dir:
        def transform(text, name):
            return extract_brief(text, rules_dir / f"{name}.md")
    else:
        transform = None

    content = compose_strings(items, transform=transform)

    if dry_run:
        print(f"  would compose {len(items)} file(s) -> {rules_file}")
    else:
        _, msg = atomic_write(rules_file, content)
        print(f"  {msg}")

    if rules_dir:
        _sync_rules_dir(items, rules_dir, dry_run)


def _resolve_and_partition(
    item_type: str, agent: str, device_name: str,
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
        targets = resolve_sync_targets({**row, "configs": configs}, agent=agent, device_name=device_name)
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


def sync_rules(agent: str, dry_run: bool, device_name: str = "") -> None:
    from scripts.shared.agents import AGENT_TARGETS

    cfg = AGENT_TARGETS[agent]
    global_rows, repo_rows = _resolve_and_partition("rule", agent, device_name)

    global_items = [(r["name"], r["content"]["body"]) for r in global_rows]
    _sync_rules_to_target(global_items, cfg, dry_run)

    def _repo_sync(rows, rcfg, dr):
        items = [(r["name"], r["content"]["body"]) for r in rows]
        _sync_rules_to_target(items, rcfg, dr)

    _sync_to_repo_targets(repo_rows, agent, "rules_file", _repo_sync, dry_run)


def _sync_rules_dir(items: list[tuple[str, str]], dest_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"  would copy {len(items)} file(s) -> {dest_dir}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    source_names = {f"{name}.md" for name, _ in items}

    for name, body in items:
        _, msg = atomic_write(dest_dir / f"{name}.md", body)
        print(f"  {msg}")

    _remove_stale(dest_dir, source_names)


def _sync_skills_to_target(skills: dict[str, dict], dest_dir: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"  would sync {len(skills)} skill(s) -> {dest_dir}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    for name, data in sorted(skills.items()):
        dest_skill = dest_dir / name
        dest_skill.mkdir(parents=True, exist_ok=True)
        _, msg = atomic_write(dest_skill / "SKILL.md", data["skill_md"])
        print(f"  {msg}")
        for rel_path, file_content in sorted(data.get("files", {}).items()):
            dest_file = dest_skill / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            _, msg = atomic_write(dest_file, file_content)
            print(f"  {msg}")

    _remove_stale(dest_dir, set(skills.keys()), match_dirs=True)


def _collect_skill_clones(
    agent: str, device_name: str,
) -> tuple[dict[str, dict], dict[str, dict[str, dict]]]:
    global_rows, repo_rows = _resolve_and_partition("rule", agent, device_name)

    def to_skills(rows: list[dict]) -> dict[str, dict]:
        return {
            r["name"]: {"skill_md": r["content"]["body"], "files": {}}
            for r in rows if r.get("clone_as_skill")
        }

    global_clones = to_skills(global_rows)
    repo_clones = {repo: to_skills(rows) for repo, rows in repo_rows.items()}
    return global_clones, repo_clones


def sync_skills(agent: str, dry_run: bool, device_name: str = "") -> None:
    from scripts.shared.agents import AGENT_TARGETS
    from services.api.models.shared.harness import content_metadata

    cfg = AGENT_TARGETS[agent]
    global_rows, repo_rows = _resolve_and_partition("skill", agent, device_name)
    global_clones, repo_clones = _collect_skill_clones(agent, device_name)

    def rows_to_skills(rows: list[dict]) -> dict[str, dict]:
        result = {}
        for r in rows:
            meta = content_metadata(r)
            result[r["name"]] = {"skill_md": r["content"]["body"], "files": meta.get("files", {})}
        return result

    global_skills = {**global_clones, **rows_to_skills(global_rows)}
    _sync_skills_to_target(global_skills, Path(cfg["skills_dir"]).expanduser(), dry_run)

    from scripts.shared.agents import repo_config as _repo_config

    all_repo_paths = set(repo_rows) | set(repo_clones)
    for repo_path in all_repo_paths:
        if not Path(repo_path).is_dir():
            print(f"  warning: repo path does not exist, skipping: {repo_path}")
            continue
        rcfg = _repo_config(agent, repo_path)
        if not rcfg.get("skills_dir"):
            continue
        clones = repo_clones.get(repo_path, {})
        real = rows_to_skills(repo_rows.get(repo_path, []))
        _sync_skills_to_target({**clones, **real}, Path(rcfg["skills_dir"]), dry_run)


def _compose_agent_file(body: str, metadata: dict, scoped_rules: list | None = None) -> str:
    parts = []
    if metadata:
        import yaml
        frontmatter = yaml.dump(metadata, default_flow_style=False).rstrip()
        parts.append(f"---\n{frontmatter}\n---\n")
    parts.append(body.rstrip())
    if scoped_rules:
        parts.append("\n\n# Rules\n")
        for rule in scoped_rules:
            parts.append(rule["content"]["body"].rstrip())
    return "\n\n".join(parts) + "\n"


def sync_agents(agent: str, dry_run: bool, device_name: str = "") -> None:
    from scripts.shared.agents import AGENT_TARGETS
    from services.api.models.agent import collect_agents_from_db

    cfg = AGENT_TARGETS[agent]
    agents_dir = cfg.get("agents_dir")
    if not agents_dir:
        return

    dest_dir = Path(agents_dir).expanduser()
    agent_defs = collect_agents_from_db(agent)

    if dry_run:
        print(f"  would sync {len(agent_defs)} agent(s) -> {dest_dir}")
        return

    dest_dir.mkdir(parents=True, exist_ok=True)
    source_names = set()

    for name, data in sorted(agent_defs.items()):
        filename = f"{name}.md"
        source_names.add(filename)
        content = _compose_agent_file(
            data["body"], data["metadata"], data.get("scoped_rules"),
        )
        _, msg = atomic_write(dest_dir / filename, content)
        print(f"  {msg}")

    _remove_stale(dest_dir, source_names)


def sync_item(item_type: str, item_id: int, device_name: str = "") -> dict:
    from services.api.models.shared.harness import get_item_by_id, _table
    from services.api.models.shared.sync import resolve_sync_targets
    from services.api.models import shared
    from scripts.shared.agents import AGENT_TARGETS
    from scripts.shared.mcp_utils import sync_mcp
    from scripts.shared.hook_utils import sync_hooks

    _table(item_type)
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

    sync_dispatch = {
        "rule": lambda a: sync_rules(a, False, device_name),
        "skill": lambda a: sync_skills(a, False, device_name),
        "tool": lambda a: sync_mcp(a, False),
        "hook": lambda a: sync_hooks(a, False),
        "agent": lambda a: sync_agents(a, False, device_name),
    }

    original = shared.harness.list_items_full
    shared.harness.list_items_full = lambda t: [item] if t == item_type else original(t)

    try:
        for agent in agents_to_sync:
            print(f"[{agent}/{item_type}]")
            sync_dispatch[item_type](agent)

            if item_type == "rule" and item.get("clone_as_skill"):
                print(f"[{agent}/skills (clone)]")
                sync_skills(agent, False, device_name)
    finally:
        shared.harness.list_items_full = original

    return {
        "success": True,
        "item_name": item["name"],
        "agents_synced": agents_to_sync,
        "message": f"Synced to {len(agents_to_sync)} agent(s): {', '.join(agents_to_sync)}",
    }
