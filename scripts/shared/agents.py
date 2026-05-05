from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import tomli_w

AGENT_TARGETS = {
    "claude": {
        "rules_file": "~/.claude/CLAUDE.md",
        "rules_dir": "~/.claude/rules/",
        "skills_dir": "~/.claude/skills/",
        "agents_dir": "~/.claude/agents/",
        "mcp_file": "~/.claude.json",
        "mcp_key": "mcpServers",
        "mcp_format": "json",
        "mcp_transform": lambda srv: {
            "type": "http", "url": srv["url"],
            **{k: srv[k] for k in ("headers", "oauth") if k in srv},
        },
        "hooks_file": "~/.claude/settings.json",
        "hooks_key": "hooks",
        "hooks_format": "json",
    },
    "codex": {
        "rules_file": "~/.codex/AGENTS.md",
        "skills_dir": "~/.codex/skills/",
        "agents_dir": "~/.codex/agents/",
        "mcp_file": "~/.codex/config.toml",
        "mcp_key": "mcp_servers",
        "mcp_format": "toml",
        "mcp_transform": lambda srv: {
            "url": srv["url"],
            **{k: srv[k] for k in ("headers",) if k in srv},
        },
        "hooks_file": "~/.codex/config.toml",
        "hooks_key": "hooks",
        "hooks_format": "toml",
    },
    "gemini": {
        "rules_file": "~/.gemini/GEMINI.md",
        "skills_dir": "~/.gemini/skills/",
        "agents_dir": "~/.gemini/agents/",
        "mcp_file": "~/.gemini/settings.json",
        "mcp_key": "mcpServers",
        "mcp_format": "json",
        "mcp_transform": lambda srv: {
            "httpUrl": srv["url"],
            **{k: srv[k] for k in ("headers",) if k in srv},
        },
        "hooks_file": "~/.gemini/settings.json",
        "hooks_key": "hooks",
        "hooks_format": "json",
    },
}


_REPO_SUBDIRS: dict[str, dict[str, str]] = {
    "claude": {
        "rules_file": ".claude/CLAUDE.md",
        "rules_dir": ".claude/rules/",
        "skills_dir": ".claude/skills/",
        "agents_dir": ".claude/agents/",
    },
    "codex": {
        "rules_file": "AGENTS.md",
        "skills_dir": ".agents/skills/",
    },
    "gemini": {
        "rules_file": ".gemini/GEMINI.md",
        "skills_dir": ".gemini/skills/",
    },
}


def repo_config(agent: str, repo_path: str) -> dict[str, str]:
    assert Path(repo_path).is_absolute(), f"repo_path must be absolute: {repo_path}"
    base = _REPO_SUBDIRS.get(agent, {})
    return {k: str(Path(repo_path) / v) for k, v in base.items()}


def _read_config(path: Path, fmt: str) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if fmt == "toml":
        return tomllib.loads(text)
    return json.loads(text)


def _write_config(path: Path, data: dict, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "toml":
        path.write_text(tomli_w.dumps(data), encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _remove_path(cfg_value: str, removed: list[str], *, tree: bool = False) -> None:
    p = Path(cfg_value).expanduser()
    if not p.exists():
        return
    shutil.rmtree(p) if tree else p.unlink()
    removed.append(str(p))


def unsync_agent(agent: str) -> list[str]:
    if agent not in AGENT_TARGETS:
        raise ValueError(f"Unknown agent: {agent!r}. Must be one of {set(AGENT_TARGETS)}")
    cfg = AGENT_TARGETS[agent]
    removed: list[str] = []

    _remove_path(cfg["rules_file"], removed)
    if "rules_dir" in cfg:
        _remove_path(cfg["rules_dir"], removed, tree=True)
    _remove_path(cfg["skills_dir"], removed, tree=True)
    if "agents_dir" in cfg:
        _remove_path(cfg["agents_dir"], removed, tree=True)

    mcp_file = Path(cfg["mcp_file"]).expanduser()
    if mcp_file.exists():
        data = _read_config(mcp_file, cfg["mcp_format"])
        if cfg["mcp_key"] in data:
            del data[cfg["mcp_key"]]
            _write_config(mcp_file, data, cfg["mcp_format"])
            removed.append(f"{mcp_file} (removed {cfg['mcp_key']})")

    removed.extend(_unsync_repo_targets(agent))

    return removed


def _unsync_repo_targets(agent: str) -> list[str]:
    removed: list[str] = []
    try:
        from services.db import get_connection
        from psycopg2.extras import RealDictCursor
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT DISTINCT repo FROM harness_configs WHERE repo != '*' AND %s = ANY(agents)",
                    (agent,),
                )
                repos = [row["repo"] for row in cur.fetchall()]
    except Exception:
        return removed

    for repo_path in repos:
        if not Path(repo_path).is_dir():
            continue
        rcfg = repo_config(agent, repo_path)
        for key in ("rules_file", "rules_dir", "skills_dir", "agents_dir"):
            path = rcfg.get(key)
            if not path:
                continue
            p = Path(path)
            if p.is_file():
                p.unlink()
                removed.append(str(p))
            elif p.is_dir():
                shutil.rmtree(p)
                removed.append(str(p))

    return removed


def unsync_all() -> list[str]:
    removed: list[str] = []
    for agent in AGENT_TARGETS:
        removed.extend(unsync_agent(agent))
    return removed
