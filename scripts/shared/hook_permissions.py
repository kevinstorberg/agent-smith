from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path

from scripts.shared.agents import _read_config
from scripts.shared.atomic_json import atomic_write_json, exclusive_file_lock


def validate_allow_rules(value: object, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of permission rules")
    for index, rule in enumerate(value):
        if not isinstance(rule, str) or not rule.strip() or rule != rule.strip() or any(c in rule for c in "\r\n\0"):
            raise ValueError(f"{label}[{index}] must be a nonblank, single-line permission rule")
    return list(value)


def validate_managed_allow_rules(value: object, label: str) -> list[str]:
    rules = validate_allow_rules(value, label)
    for rule in rules:
        if re.fullmatch(r"mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+", rule):
            continue
        prefix = rule[5:-3]
        try:
            command = shlex.split(prefix)
        except ValueError:
            command = []
        paths_absolute = len(command) >= 2 and all(token.startswith(("/", "${REPO_ROOT}/")) for token in command[:2])
        if (rule.startswith("Bash(") and rule.endswith(" *)")
                and not any(c in prefix for c in "*?[];&|<>`") and "$(" not in prefix
                and paths_absolute
                and re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", command[0].rsplit("/", 1)[-1])
                and command[1].endswith(".py")):
            continue
        raise ValueError(f"{label} requires an exact MCP tool or a fixed Python interpreter and script prefix")
    return rules


def ownership_path(settings_path: Path) -> Path:
    return settings_path.with_name(f".{settings_path.name}.agent-smith-hooks.json")


def _fingerprint(rules: list[str]) -> str:
    return hashlib.sha256(json.dumps(rules, ensure_ascii=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _allow_rules(settings: dict) -> list[str]:
    permissions = settings.get("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError("Claude settings.permissions must be an object")
    return validate_allow_rules(permissions.get("allow", []), "Claude settings.permissions.allow")


def _ownership(path: Path, current: list[str]) -> list[str]:
    if path.is_symlink():
        raise ValueError(f"Refusing to read symbolic hook permission ownership state: {path}")
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError(f"Cannot read hook permission ownership state: {path}") from exc
    if not isinstance(state, dict) or type(state.get("version")) is not int or state["version"] != 1:
        raise ValueError(f"Unsupported hook permission ownership state: {path}")
    owned = validate_allow_rules(state.get("owned_rules"), "Hook permission owned_rules")
    pending = state.get("pending")
    if pending is None:
        return owned
    if not isinstance(pending, dict):
        raise ValueError(f"Invalid pending hook permission transaction: {path}")
    next_owned = validate_allow_rules(pending.get("owned_rules"), "Pending hook permission owned_rules")
    for key in ("before", "after"):
        digest = pending.get(key)
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"Invalid pending hook permission fingerprint: {path}")
    fingerprint = _fingerprint(current)
    if fingerprint == pending["after"]:
        owned = next_owned
    elif fingerprint != pending["before"]:
        raise RuntimeError(
            f"Claude allow rules changed during an interrupted hook Sync; inspect ownership state at {path} before retrying"
        )
    atomic_write_json(path, {"version": 1, "owned_rules": owned})
    return owned


def sync_claude_hook_settings(settings_path: Path, hooks: dict, allowed_tools: list[str]) -> bool:
    if not isinstance(hooks, dict):
        raise ValueError("Claude hooks must be an object")
    desired = list(dict.fromkeys(validate_managed_allow_rules(allowed_tools, "Hook permissions.allow")))
    settings_path = Path(settings_path)
    state_path = ownership_path(settings_path)
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    with exclusive_file_lock(lock_path, "Claude hook Sync"):
        settings = _read_config(settings_path, "json")
        if not isinstance(settings, dict):
            raise ValueError("Claude settings must be a JSON object")
        current = _allow_rules(settings)
        owned = _ownership(state_path, current)
        retired = set(owned) - set(desired)
        target = [rule for rule in current if rule not in retired]
        target.extend(rule for rule in desired if rule not in target)
        next_owned = list(dict.fromkeys(
            [rule for rule in owned if rule in desired] + [rule for rule in desired if rule not in current]
        ))
        updated = {**settings, "hooks": hooks}
        if target or "allow" in settings.get("permissions", {}):
            updated["permissions"] = {**settings.get("permissions", {}), "allow": target}
        if updated == settings and next_owned == owned:
            return False

        # The intent must survive a crash on either side of replacing settings.
        atomic_write_json(state_path, {
            "version": 1,
            "owned_rules": owned,
            "pending": {"before": _fingerprint(current), "after": _fingerprint(target), "owned_rules": next_owned},
        })
        if _read_config(settings_path, "json") != settings:
            raise RuntimeError("Claude settings changed during hook Sync; no settings were overwritten")
        changed = atomic_write_json(settings_path, updated)
        atomic_write_json(state_path, {"version": 1, "owned_rules": next_owned})
        return changed
