from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path

import tomli_w

from scripts.shared.agents import AGENT_TARGETS, _read_config
from scripts.shared.env import env_references, expand_env, read_env_file
from scripts.shared.fs import atomic_write
from scripts.shared.paths import REPO_ROOT

SECRET_NAME = re.compile(r"TOKEN|KEY|SECRET|PASSWORD")


def unusable_env_references(server: dict, environ: Mapping[str, str], defaults: Mapping[str, str]) -> list[str]:
    """The ${VAR}s a server config needs that are unset, or are secrets still holding their .env.default placeholder."""
    return sorted(
        name
        for name in env_references(server)
        if not environ.get(name) or (SECRET_NAME.search(name) and environ[name] == defaults.get(name))
    )


def sync_mcp(agent: str, dry_run: bool) -> list[str]:
    """Deploy the agent's MCP servers, withholding any whose config can't work; returns one error per withheld server."""
    from services.api.models.tool import collect_tools_from_db

    cfg = AGENT_TARGETS[agent]
    dest = Path(cfg["mcp_file"]).expanduser()

    defaults = read_env_file(REPO_ROOT / ".env.default")
    app_env = os.environ.get("APP_ENV", "development")
    servers, errors = {}, []
    for name, srv in collect_tools_from_db(agent).items():
        unusable = unusable_env_references(srv, os.environ, defaults)
        if unusable:
            errors.append(
                f"{name} not deployed to {agent}: set {', '.join(unusable)} in .env.{app_env} "
                "(unset, or still the .env.default placeholder)"
            )
        else:
            servers[name] = expand_env(srv)
    for error in errors:
        print(f"  ERROR {error}")

    if dry_run:
        print(f"  would sync {len(servers)} server(s) -> {dest}")
        return errors

    data = _read_config(dest, cfg["mcp_format"]) if dest.exists() else {}
    data[cfg["mcp_key"]] = {
        name: cfg["mcp_transform"](srv) for name, srv in servers.items()
    }

    if cfg["mcp_format"] == "toml":
        _, msg = atomic_write(dest, tomli_w.dumps(data))
    else:
        _, msg = atomic_write(dest, json.dumps(data, indent=2) + "\n")
    print(f"  {msg}")
    return errors
