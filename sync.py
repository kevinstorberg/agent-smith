#!/usr/bin/env -S .venv/bin/python3
"""
sync.py

Thin orchestrator: reads harness.yaml, discovers scripts/<agent>/<type>.py,
and calls each script's main(harness_root, type_config, dry_run).

Adding a new agent or sync type (skills, tools) requires no changes here —
just add the script and the corresponding section in harness.yaml.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import yaml


def find_repo_root(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not (p / "harness.yaml").is_file():
            raise FileNotFoundError(f"harness.yaml not found at {p}")
        return p

    here = Path(__file__).resolve().parent
    for candidate in [here, *here.parents]:
        if (candidate / "harness.yaml").is_file():
            return candidate

    raise FileNotFoundError(
        "Could not locate harness.yaml. Run from your repo or pass --harness-dir."
    )


def load_harness(repo_root: Path) -> dict:
    return yaml.safe_load((repo_root / "harness.yaml").read_text(encoding="utf-8"))


def discover_scripts(repo_root: Path, agent_names: list[str]) -> list[tuple[str, str, Path]]:
    """Return (agent, type, path) for every scripts/<agent>/<type>.py that exists."""
    scripts_dir = repo_root / "scripts"
    found = []
    for agent in agent_names:
        agent_dir = scripts_dir / agent
        if not agent_dir.is_dir():
            continue
        for script_path in sorted(agent_dir.glob("*.py")):
            if not script_path.stem.startswith("_"):
                found.append((agent, script_path.stem, script_path))
    return found


def call_script(
    repo_root: Path,
    agent: str,
    type_name: str,
    script_path: Path,
    type_config: dict,
    dry_run: bool,
) -> None:
    from scripts.shared.paths import ensure_importable
    ensure_importable()

    spec = importlib.util.spec_from_file_location(
        f"scripts.{agent}.{type_name}", script_path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if hasattr(module, "main"):
        module.main(repo_root, type_config, dry_run)
    else:
        print(f"  warning: {script_path} has no main() — skipped")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sync.py",
        description="Sync harness content to agent config files via per-agent scripts",
    )
    parser.add_argument(
        "--harness-dir",
        default=None,
        help="Repo root (defaults to searching upward for harness.yaml)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without writing files",
    )
    args = parser.parse_args()

    repo_root = find_repo_root(args.harness_dir)

    from scripts.shared.paths import ensure_importable
    ensure_importable()

    from scripts.shared.env import load_dotenv
    load_dotenv(repo_root)

    harness = load_harness(repo_root)
    agents: dict = harness.get("agents", {})

    scripts = discover_scripts(repo_root, list(agents))
    if not scripts:
        print("No scripts found under scripts/<agent>/*.py")
        return 0

    for agent, type_name, script_path in scripts:
        type_config = agents[agent].get(type_name)
        if type_config is None:
            print(
                f"warning: {script_path.relative_to(repo_root)} found but "
                f"harness.yaml has no [{agent}][{type_name}] section — skipped"
            )
            continue
        print(f"[{agent}/{type_name}]")
        call_script(repo_root, agent, type_name, script_path, type_config, args.dry_run)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
