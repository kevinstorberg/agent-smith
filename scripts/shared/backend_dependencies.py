from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from scripts.shared.atomic_json import atomic_write_json, exclusive_file_lock

_IDENTITY = "import json,sys; print(json.dumps({'prefix':sys.prefix,'base_prefix':sys.base_prefix,'version':list(sys.version_info[:3]),'executable':sys.executable}))"
_HOST_ENVIRONMENT = {
    "PATH",
    "HOME",
    "TMPDIR",
    "TMP",
    "TEMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SYSTEMROOT",
    "WINDIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "PIP_INDEX_URL",
    "PIP_EXTRA_INDEX_URL",
    "PIP_TRUSTED_HOST",
    "PIP_CERT",
    "PIP_CLIENT_CERT",
    "PIP_CACHE_DIR",
    "PIP_PROXY",
}


def _environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in _HOST_ENVIRONMENT}
    # Hidden pip configuration must not force upgrades or redirect the owned destination.
    env["PIP_CONFIG_FILE"] = os.devnull
    return env


def _run(command: list[str], *, timeout: int, capture: bool = True):
    try:
        return subprocess.run(
            command,
            env=_environment(),
            text=True,
            capture_output=capture,
            timeout=timeout,
            check=True,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Backend dependencies timed out after {timeout} seconds; retry ./run.sh after checking package index connectivity"
        ) from None
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"Backend dependencies command failed with exit {error.returncode}; check package availability, compatibility and index connectivity"
        ) from None
    except OSError:
        raise RuntimeError(
            "Backend dependencies could not run the selected Python/pip executable"
        ) from None


def _identity(python: str) -> dict:
    result = _run([python, "-I", "-c", _IDENTITY], timeout=30)
    try:
        identity = json.loads(result.stdout)
        prefix = Path(identity["prefix"])
        base = Path(identity["base_prefix"])
        version = identity["version"]
        valid = (
            prefix.is_absolute()
            and prefix.is_dir()
            and prefix.resolve() != base.resolve()
            and isinstance(version, list)
            and len(version) == 3
            and all(type(part) is int for part in version)
            and version[:2] == [3, 13]
            and isinstance(identity["executable"], str)
            and Path(identity["executable"]).is_absolute()
        )
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise RuntimeError(
            "Backend dependencies require an initialized Python 3.13 virtual environment"
        )
    return identity


def ensure_backend_dependencies(
    root: Path, python: str, *, upgrade: bool = False
) -> bool:
    root = Path(root)
    requirements = root / "requirements.txt"
    if not requirements.is_file():
        raise RuntimeError("Backend dependencies require requirements.txt")
    executable = Path(python).absolute()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(
            "Backend dependencies require an executable Python virtual environment"
        )
    if type(upgrade) is not bool:
        raise ValueError("Backend dependency upgrade must be a boolean")
    python = str(executable)
    print("Backend dependencies: checking declared requirements", flush=True)
    try:
        identity = _identity(python)
        prefix = Path(identity["prefix"]).resolve()
        with exclusive_file_lock(
            prefix / ".agent-smith-dependencies.lock", "Backend dependencies"
        ):
            receipt = prefix / ".agent-smith-requirements-hash"
            if receipt.is_symlink():
                raise ValueError(
                    f"Refusing a symbolic link dependency receipt: {receipt}"
                )
            if _identity(python) != identity:
                raise RuntimeError(
                    "Backend dependencies interpreter changed during preparation"
                )
            fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
            with tempfile.TemporaryDirectory(
                prefix="agent-smith-dependencies-"
            ) as temporary:
                report = Path(temporary) / "install.json"
                command = [
                    python,
                    "-I",
                    "-m",
                    "pip",
                    "--disable-pip-version-check",
                    "--no-input",
                    "--require-virtualenv",
                    "install",
                    "--quiet",
                    "--retries",
                    "0",
                    "--timeout",
                    "15",
                    "--prefix",
                    str(prefix),
                    "--report",
                    str(report),
                    "-r",
                    str(requirements),
                ]
                if upgrade:
                    command.append("--upgrade")
                _run(command, timeout=600, capture=False)
                try:
                    installed = json.loads(report.read_text())["install"]
                    if not isinstance(installed, list) or not all(
                        isinstance(row, dict) for row in installed
                    ):
                        raise ValueError
                except (OSError, ValueError, KeyError, TypeError):
                    raise RuntimeError(
                        "Backend dependencies returned an invalid installation report"
                    ) from None
            _run(
                [
                    python,
                    "-I",
                    "-m",
                    "pip",
                    "--disable-pip-version-check",
                    "--require-virtualenv",
                    "check",
                ],
                timeout=30,
                capture=False,
            )
            if (
                hashlib.sha256(requirements.read_bytes()).hexdigest() != fingerprint
                or _identity(python) != identity
            ):
                raise RuntimeError(
                    "Backend dependencies inputs changed during installation; rerun ./run.sh"
                )
            atomic_write_json(
                receipt,
                {"version": 1, "requirements_sha256": fingerprint, "python": identity},
            )
        print(
            f"Backend dependencies: ready ({len(installed)} packages installed)",
            flush=True,
        )
        return bool(installed)
    except (OSError, RuntimeError, ValueError):
        print("Backend dependencies: failed; application startup stopped", flush=True)
        raise
