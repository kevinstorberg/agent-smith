from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
COMMAND_TIMEOUT = 30
INSTALL_TIMEOUT = 600
AUDIT_TIMEOUT = 300


class CIAuditError(RuntimeError):
    pass


def clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in ("PYTHONHOME", "PYTHONPATH", "PIPAPI_PYTHON_LOCATION", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return environment


def run(
    command: list[str], *, timeout: int = COMMAND_TIMEOUT, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        env=clean_environment(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def interpreter(path: str | Path) -> Path:
    # Resolving the executable symlink would bypass its virtual environment.
    selected = Path(path).expanduser().absolute()
    if not selected.is_file() or not os.access(selected, os.X_OK):
        raise CIAuditError(f"Python interpreter is not executable: {selected}")
    return selected


def ruff_requirement(requirements: Path) -> str:
    candidates = []
    for raw in requirements.read_text().splitlines():
        line = raw.partition("#")[0].strip()
        if re.match(r"ruff(?:[^A-Za-z0-9_.-]|$)", line, re.IGNORECASE):
            candidates.append(line)
    if (
        len(candidates) != 1
        or re.fullmatch(r"ruff==[0-9]+\.[0-9]+\.[0-9]+", candidates[0]) is None
    ):
        raise CIAuditError(
            "requirements.txt must contain exactly one stable numeric ruff==version pin"
        )
    return candidates[0]


def setup_tools(directory: Path, *, repository: Path = ROOT) -> Path:
    requirement = ruff_requirement(repository / "requirements.txt")
    tools_requirements = repository / "requirements-ci.txt"
    if not tools_requirements.is_file():
        raise CIAuditError("requirements-ci.txt is missing")
    directory = directory.expanduser().absolute()
    if (
        directory.is_symlink()
        or directory.exists()
        and not (directory / "pyvenv.cfg").is_file()
    ):
        raise CIAuditError(
            f"CI tools directory is not an owned virtual environment: {directory}"
        )
    run([sys.executable, "-m", "venv", str(directory)], timeout=INSTALL_TIMEOUT)
    python = interpreter(directory / "bin" / "python")
    installed = run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "-r",
            str(tools_requirements),
            requirement,
        ],
        timeout=INSTALL_TIMEOUT,
    )
    print(installed.stdout, end="")
    print(run([str(python), "-m", "pip", "check"]).stdout, end="")
    actual = run([str(python), "-m", "ruff", "--version"]).stdout.strip()
    if actual != f"ruff {requirement.partition('==')[2]}":
        raise CIAuditError(f"Installed Ruff does not match requirements.txt: {actual}")
    return python


def packages(rows: Any, *, label: str) -> dict[str, Version]:
    from packaging.utils import canonicalize_name
    from packaging.version import Version

    if not isinstance(rows, list) or not rows:
        raise CIAuditError(f"{label} must contain a nonempty package list")
    result: dict[str, Version] = {}
    for row in rows:
        if not isinstance(row, dict) or "skip_reason" in row:
            raise CIAuditError(f"{label} contains a malformed or skipped package")
        if not isinstance(row.get("name"), str) or not isinstance(
            row.get("version"), str
        ):
            raise CIAuditError(f"{label} package name and version must be strings")
        try:
            name = canonicalize_name(row["name"], validate=True)
            version = Version(row["version"])
        except ValueError as error:
            raise CIAuditError(
                f"{label} contains an invalid package name or PEP440 version"
            ) from error
        if name in result:
            raise CIAuditError(
                f"{label} contains duplicate or conflicting package: {name}"
            )
        result[name] = version
    return result


def parse_json(value: str, *, label: str) -> Any:
    try:
        return json.loads(value)
    except ValueError as error:
        raise CIAuditError(f"{label} did not return valid JSON") from error


def validate_report(report: Any, expected: dict[str, Version]) -> None:
    if not isinstance(report, dict):
        raise CIAuditError("pip-audit must return a JSON object")
    observed = packages(report.get("dependencies"), label="pip-audit dependencies")
    if observed != expected:
        missing = sorted(set(expected) - set(observed))
        extra = sorted(set(observed) - set(expected))
        changed = sorted(
            name
            for name in expected.keys() & observed.keys()
            if expected[name] != observed[name]
        )
        raise CIAuditError(
            f"Incomplete pip-audit coverage: missing={missing}, extra={extra}, changed_versions={changed}"
        )
    for row in report["dependencies"]:
        if not isinstance(row.get("vulns"), list):
            raise CIAuditError(
                "pip-audit dependencies must include vulnerability lists"
            )
        if row["vulns"]:
            raise CIAuditError(
                f"pip-audit reported vulnerabilities for {row['name']}: {json.dumps(row['vulns'])}"
            )


def audit_environment(python: Path, tools_python: Path, *, label: str) -> int:
    print(f"Checking {label} dependency compatibility", flush=True)
    print(run([str(python), "-m", "pip", "check"]).stdout, end="")
    inventory = packages(
        parse_json(
            run([str(python), "-m", "pip", "list", "--format=json"]).stdout,
            label=f"{label} pip list",
        ),
        label=f"{label} installed inventory",
    )
    with tempfile.TemporaryDirectory(prefix="agent-smith-pip-audit-") as temporary:
        requirements = Path(temporary) / "installed.txt"
        requirements.write_text(
            "".join(
                f"{name}=={version}\n" for name, version in sorted(inventory.items())
            )
        )
        result = run(
            [
                str(tools_python),
                "-m",
                "pip_audit",
                "--requirement",
                str(requirements),
                "--no-deps",
                "--disable-pip",
                "--strict",
                "--format",
                "json",
            ],
            timeout=AUDIT_TIMEOUT,
        )
        validate_report(parse_json(result.stdout, label="pip-audit"), inventory)
    print(
        f"{label}: audited all {len(inventory)} installed packages; no skipped packages or known vulnerabilities",
        flush=True,
    )
    return len(inventory)


def audit(python: Path, tools_python: Path) -> None:
    python, tools_python = interpreter(python), interpreter(tools_python)
    audit_environment(python, tools_python, label="Application")
    if python != tools_python:
        audit_environment(tools_python, tools_python, label="CI tools")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Set up isolated Python CI tools and completely audit installed packages"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("setup-tools")
    setup.add_argument("--directory", type=Path, required=True)
    check = commands.add_parser("audit")
    check.add_argument("--python", type=Path, required=True)
    check.add_argument("--tools-python", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "setup-tools":
            print(f"CI tools interpreter: {setup_tools(args.directory)}")
        else:
            audit(args.python, args.tools_python)
    except subprocess.CalledProcessError as error:
        print(error.stdout or "", file=sys.stderr, end="")
        print(error.stderr or "", file=sys.stderr, end="")
        print(
            f"CI command failed with exit {error.returncode}: {error.cmd}",
            file=sys.stderr,
        )
        return error.returncode if error.returncode > 0 else 1
    except (CIAuditError, OSError, subprocess.TimeoutExpired) as error:
        print(f"Python CI check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
