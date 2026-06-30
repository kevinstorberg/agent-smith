from __future__ import annotations

import json
import shutil
import time
import tomllib
from pathlib import Path

import tomli_w

# Harness consumers that run in-process (e.g. the opinion graph) rather than
# syncing config files to disk. Assignable to items, never sync/unsync targets.
VIRTUAL_AGENTS: tuple[str, ...] = ("opinion", "curator")

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


class ConfigUnreadableError(RuntimeError):
    """A destination config file could not be parsed after retrying.

    Raised only for genuine, non-transient corruption — torn reads (the file
    caught mid-write by the live agent app) heal on retry and never reach here.
    Carries the file path and parse location so the broken file is actionable,
    and crashing here guarantees we never overwrite a file we couldn't read.
    """

    def __init__(self, path: Path, cause: Exception, attempts: int) -> None:
        self.path = path
        self.cause = cause
        lineno = getattr(cause, "lineno", None)
        colno = getattr(cause, "colno", None)
        loc = f" at line {lineno}, column {colno}" if lineno is not None else ""
        super().__init__(
            f"{path} is not valid after {attempts} attempt(s){loc}: {cause}. "
            f"Left unchanged (not overwritten). Fix the file, then re-run sync."
        )


# Parse failures that a re-read can resolve: a torn read yields invalid JSON/TOML,
# or invalid UTF-8 if caught mid multi-byte write.
_TRANSIENT_PARSE_ERRORS = (json.JSONDecodeError, tomllib.TOMLDecodeError, UnicodeDecodeError)


def read_with_retry(
    path: Path, fmt: str, *, max_attempts: int | None = None, backoff: float | None = None
) -> dict:
    """Read+parse a live config file, retrying torn reads before giving up.

    The destination files are rewritten continuously by the running agent app,
    so a single read can catch the file mid-write. We re-read up to
    SYNC_READ_MAX_ATTEMPTS times with SYNC_READ_BACKOFF between tries; the live
    write completes in milliseconds, so a retry catches a consistent file. If it
    is still unparseable after the last attempt, the corruption is real, not
    transient — raise ConfigUnreadableError and crash rather than risk a write.

    Knobs are resolved lazily from services.config (which imports this module, so
    a top-level import would be circular); tests pass them explicitly.
    """
    if max_attempts is None or backoff is None:
        from services.config import SYNC_READ_BACKOFF, SYNC_READ_MAX_ATTEMPTS

        max_attempts = SYNC_READ_MAX_ATTEMPTS if max_attempts is None else max_attempts
        backoff = SYNC_READ_BACKOFF if backoff is None else backoff

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            text = path.read_text(encoding="utf-8")
            return tomllib.loads(text) if fmt == "toml" else json.loads(text)
        except _TRANSIENT_PARSE_ERRORS as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(backoff)
    raise ConfigUnreadableError(path, last_error, max_attempts)


def _read_config(path: Path, fmt: str) -> dict:
    if not path.exists():
        return {}
    return read_with_retry(path, fmt)


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
