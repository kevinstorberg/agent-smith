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
        "mcp_file": "~/.claude.json",
        "mcp_key": "mcpServers",
        "mcp_format": "json",
        "mcp_transform": lambda srv: {
            "type": "http", "url": srv["url"],
            **{k: srv[k] for k in ("headers", "oauth") if k in srv},
        },
    },
    "codex": {
        "rules_file": "~/.codex/AGENTS.md",
        "skills_dir": "~/.codex/skills/",
        "mcp_file": "~/.codex/config.toml",
        "mcp_key": "mcp_servers",
        "mcp_format": "toml",
        "mcp_transform": lambda srv: {
            "url": srv["url"],
            **{k: srv[k] for k in ("headers",) if k in srv},
        },
    },
    "gemini": {
        "rules_file": "~/.gemini/GEMINI.md",
        "skills_dir": "~/.gemini/skills/",
        "mcp_file": "~/.gemini/settings.json",
        "mcp_key": "mcpServers",
        "mcp_format": "json",
        "mcp_transform": lambda srv: {
            "httpUrl": srv["url"],
            **{k: srv[k] for k in ("headers",) if k in srv},
        },
    },
}


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


def unsync_agent(agent: str) -> list[str]:
    if agent not in AGENT_TARGETS:
        raise ValueError(f"Unknown agent: {agent!r}. Must be one of {set(AGENT_TARGETS)}")
    cfg = AGENT_TARGETS[agent]
    removed: list[str] = []

    rules_file = Path(cfg["rules_file"]).expanduser()
    if rules_file.exists():
        rules_file.unlink()
        removed.append(str(rules_file))

    if "rules_dir" in cfg:
        rules_dir = Path(cfg["rules_dir"]).expanduser()
        if rules_dir.exists():
            shutil.rmtree(rules_dir)
            removed.append(str(rules_dir))

    skills_dir = Path(cfg["skills_dir"]).expanduser()
    if skills_dir.exists():
        shutil.rmtree(skills_dir)
        removed.append(str(skills_dir))

    mcp_file = Path(cfg["mcp_file"]).expanduser()
    if mcp_file.exists():
        data = _read_config(mcp_file, cfg["mcp_format"])
        if cfg["mcp_key"] in data:
            del data[cfg["mcp_key"]]
            _write_config(mcp_file, data, cfg["mcp_format"])
            removed.append(f"{mcp_file} (removed {cfg['mcp_key']})")

    return removed


def unsync_all() -> list[str]:
    removed: list[str] = []
    for agent in AGENT_TARGETS:
        removed.extend(unsync_agent(agent))
    return removed
