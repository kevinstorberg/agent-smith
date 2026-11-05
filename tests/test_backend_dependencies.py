from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from scripts.shared import backend_dependencies as dependencies
from scripts.shared.atomic_json import exclusive_file_lock


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    root.mkdir()
    requirements = root / "requirements.txt"
    requirements.write_text("boto3[crt]>=1.41,<2\nprometheus-client>=0.26,<1\n")
    prefix = tmp_path / "environment"
    prefix.mkdir()
    python = prefix / "bin/python"
    python.parent.mkdir()
    python.write_text("temporary interpreter")
    python.chmod(0o700)
    state = SimpleNamespace(
        identity={
            "prefix": str(prefix),
            "base_prefix": "/base",
            "version": [3, 13, 15],
            "executable": str(python),
        },
        calls=[],
        installed=True,
        failure=None,
        drift=None,
        malformed=False,
    )

    def run(command, **kwargs):
        state.calls.append((command, kwargs))
        if "-c" in command:
            return SimpleNamespace(returncode=0, stdout=json.dumps(state.identity))
        operation = "install" if "install" in command else "check"
        if state.failure == operation:
            raise subprocess.CalledProcessError(1, command)
        if state.failure == operation + " timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if operation == "install":
            report = Path(command[command.index("--report") + 1])
            report.write_text(
                json.dumps(
                    {
                        "install": "invalid"
                        if state.malformed
                        else ([{}] if state.installed else [])
                    }
                )
            )
            (prefix / "package-marker").write_text("satisfied")
            if state.drift == "requirements":
                requirements.write_text("changed-during-install\n")
            elif state.drift == "interpreter":
                state.identity["version"] = [3, 13, 16]
        return SimpleNamespace(returncode=0, stdout="No broken requirements found.\n")

    monkeypatch.setattr(dependencies.subprocess, "run", run)
    return root, python, prefix, state


def test_installs_complete_manifest_and_atomically_records_verified_success(
    installation,
):
    root, python, prefix, state = installation
    assert dependencies.ensure_backend_dependencies(root, str(python)) is True
    command, options = next((c, o) for c, o in state.calls if "install" in c)
    assert command[:4] == [str(python), "-I", "-m", "pip"]
    assert command[command.index("--prefix") + 1] == str(prefix)
    assert command[command.index("-r") + 1] == str(root / "requirements.txt")
    assert "--upgrade" not in command and "--require-virtualenv" in command
    assert options["timeout"] == 600
    assert any("check" in c for c, _ in state.calls)
    assert next(o for c, o in state.calls if "check" in c)["capture_output"] is False
    receipt = json.loads((prefix / ".agent-smith-requirements-hash").read_text())
    assert (
        receipt["requirements_sha256"]
        == hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest()
    )
    assert receipt["python"] == state.identity


def test_receipt_never_suppresses_pip_and_identical_noop_does_not_rewrite_it(
    installation,
):
    root, python, prefix, state = installation
    dependencies.ensure_backend_dependencies(root, str(python))
    receipt = prefix / ".agent-smith-requirements-hash"
    before = receipt.stat().st_mtime_ns, receipt.read_bytes()
    state.installed = False
    assert dependencies.ensure_backend_dependencies(root, str(python)) is False
    assert sum("install" in c for c, _ in state.calls) == 2
    assert (receipt.stat().st_mtime_ns, receipt.read_bytes()) == before


def test_legacy_hash_never_skips_actual_package_validation(installation):
    root, python, prefix, state = installation
    receipt = prefix / ".agent-smith-requirements-hash"
    receipt.write_text(
        hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest()
    )
    assert dependencies.ensure_backend_dependencies(root, str(python)) is True
    assert sum("install" in c for c, _ in state.calls) == 1
    assert json.loads(receipt.read_text())["version"] == 1


@pytest.mark.parametrize("upgrade", [False, True])
def test_upgrade_is_explicit_only(installation, upgrade):
    root, python, _, state = installation
    dependencies.ensure_backend_dependencies(root, str(python), upgrade=upgrade)
    command = next(c for c, _ in state.calls if "install" in c)
    assert ("--upgrade" in command) is upgrade


@pytest.mark.parametrize(
    "failure", ["install", "check", "install timeout", "check timeout"]
)
def test_failure_is_bounded_and_never_writes_success_receipt(installation, failure):
    root, python, prefix, state = installation
    state.failure = failure
    with pytest.raises(RuntimeError, match="dependencies"):
        dependencies.ensure_backend_dependencies(root, str(python))
    assert not (prefix / ".agent-smith-requirements-hash").exists()
    assert sum("install" in c for c, _ in state.calls) == 1


@pytest.mark.parametrize("drift", ["requirements", "interpreter"])
def test_changed_inputs_never_stamp_success(installation, drift):
    root, python, prefix, state = installation
    state.drift = drift
    with pytest.raises(RuntimeError, match="changed"):
        dependencies.ensure_backend_dependencies(root, str(python))
    assert not (prefix / ".agent-smith-requirements-hash").exists()


def test_system_python_is_rejected_before_installation(installation):
    root, python, prefix, state = installation
    state.identity["base_prefix"] = str(prefix)
    with pytest.raises(RuntimeError, match="virtual environment"):
        dependencies.ensure_backend_dependencies(root, str(python))
    assert not any("install" in c for c, _ in state.calls)


@pytest.mark.parametrize("kind", ["receipt", "lock"])
def test_symlink_state_is_rejected_without_modifying_target(installation, kind):
    root, python, prefix, state = installation
    target = prefix / "unrelated"
    target.write_text("preserve")
    name = (
        ".agent-smith-requirements-hash"
        if kind == "receipt"
        else ".agent-smith-dependencies.lock"
    )
    (prefix / name).symlink_to(target)
    with pytest.raises((RuntimeError, ValueError), match="symbolic link"):
        dependencies.ensure_backend_dependencies(root, str(python))
    assert target.read_text() == "preserve"
    assert not any("install" in c for c, _ in state.calls)


def test_contending_environment_lock_fails_before_pip(installation):
    root, python, prefix, state = installation
    with exclusive_file_lock(prefix / ".agent-smith-dependencies.lock"):
        with pytest.raises(RuntimeError, match="already running"):
            dependencies.ensure_backend_dependencies(root, str(python))
    assert not any("install" in c for c, _ in state.calls)


def test_package_configuration_cannot_redirect_force_upgrade_or_receive_app_secrets(
    installation, monkeypatch
):
    root, python, _, state = installation
    for key in [
        "PIP_TARGET",
        "PIP_PREFIX",
        "PIP_USER",
        "PIP_ROOT",
        "PIP_UPGRADE",
        "PIP_FORCE_REINSTALL",
        "PYTHONPATH",
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL_PRODUCTION",
    ]:
        monkeypatch.setenv(key, "private-sentinel")
    monkeypatch.setenv("PIP_INDEX_URL", "https://example.invalid/simple")
    dependencies.ensure_backend_dependencies(root, str(python))
    for _, kwargs in state.calls:
        env = kwargs["env"]
        assert "private-sentinel" not in env.values()
        assert env["PIP_INDEX_URL"] == "https://example.invalid/simple"
        assert env["PIP_CONFIG_FILE"] == os.devnull


def test_malformed_install_report_never_stamps_success(installation):
    root, python, prefix, state = installation
    state.malformed = True
    with pytest.raises(RuntimeError, match="report"):
        dependencies.ensure_backend_dependencies(root, str(python))
    assert not (prefix / ".agent-smith-requirements-hash").exists()
