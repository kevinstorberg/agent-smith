from __future__ import annotations

import hashlib
import json
import os
import shutil
import tomllib
from pathlib import Path

import tomli_w

from src.settings import get_settings

BASE_AGENT_TARGETS = {
    "claude": {
        "rules_file": "~/.claude/CLAUDE.md",
        "rules_dir": "~/.claude/rules/",
        "skills_dir": "~/.claude/skills/",
        "agents_dir": "~/.claude/agents/",
        "mcp_file": "~/.claude.json",
        "mcp_key": "mcpServers",
        "mcp_format": "json",
        "mcp_transform": lambda server: {
            "type": "http",
            "url": server["url"],
            **{key: server[key] for key in ("headers", "oauth") if key in server},
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
        "mcp_transform": lambda server: {
            "url": server["url"],
            **{key: server[key] for key in ("headers",) if key in server},
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
        "mcp_transform": lambda server: {
            "httpUrl": server["url"],
            **{key: server[key] for key in ("headers",) if key in server},
        },
        "hooks_file": "~/.gemini/settings.json",
        "hooks_key": "hooks",
        "hooks_format": "json",
    },
}

REPO_SUBDIRS: dict[str, dict[str, str]] = {
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

PATH_KEYS = {
    "rules_file",
    "rules_dir",
    "skills_dir",
    "agents_dir",
    "mcp_file",
    "hooks_file",
}


def sandbox_root() -> Path | None:
    settings = get_settings()
    root = settings.AGENT_SMITH_SYNC_ROOT.strip()
    if not root:
        if settings.AGENT_SMITH_SYNC_ALLOW_REAL_TARGETS:
            return None
        raise RuntimeError(
            "AGENT_SMITH_SYNC_ROOT is empty and AGENT_SMITH_SYNC_ALLOW_REAL_TARGETS is false. "
            "Set a sandbox root or explicitly enable real targets."
        )
    return Path(root).expanduser()


def agent_targets() -> dict[str, dict]:
    root = sandbox_root()
    targets = {}
    for agent, config in BASE_AGENT_TARGETS.items():
        resolved = dict(config)
        if root is not None:
            for key in PATH_KEYS:
                if key in resolved and resolved[key].startswith("~/"):
                    resolved[key] = str(root / resolved[key][2:])
        targets[agent] = resolved
    return targets


def repo_config(agent: str, repo_path: str) -> dict[str, str]:
    if not Path(repo_path).is_absolute():
        raise ValueError(f"repo_path must be absolute: {repo_path}")
    root = sandbox_root()
    target_root = Path(repo_path) if root is None else root / "repos" / _repo_slug(repo_path)
    return {key: str(target_root / relative) for key, relative in REPO_SUBDIRS.get(agent, {}).items()}


def read_config(path: Path, fmt: str) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if fmt == "toml":
        return tomllib.loads(text)
    return json.loads(text)


def write_config(path: Path, data: dict, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "toml":
        path.write_text(tomli_w.dumps(data), encoding="utf-8")
    else:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def remove_path(path_value: str, removed: list[str], *, tree: bool = False) -> None:
    path = Path(path_value).expanduser()
    if not path.exists():
        return
    shutil.rmtree(path) if tree else path.unlink()
    removed.append(str(path))


def expand_env(value):
    if isinstance(value, str):
        import re

        return re.sub(r"\$\{(\w+)\}", lambda match: os.environ.get(match.group(1), match.group(0)), value)
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    return value


def _repo_slug(repo_path: str) -> str:
    digest = hashlib.sha256(repo_path.encode("utf-8")).hexdigest()[:12]
    return f"{Path(repo_path).name}-{digest}"
