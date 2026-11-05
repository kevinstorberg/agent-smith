from __future__ import annotations

import sys
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest

from scripts import manage, setup
from scripts.shared.native_startup import StartupError
from tests.test_native_startup import FakeLease, launch_args


@pytest.fixture
def prepared_launch(tmp_path, monkeypatch):
    calls = []

    @contextmanager
    def lock(root, mode):
        calls.append(("lock", mode))
        yield 99

    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(manage, "instance_lock", lock)
    monkeypatch.setattr(manage, "assert_port_clear", lambda port: calls.append("clear"))
    monkeypatch.setattr(
        manage,
        "ensure_backend_dependencies",
        lambda root, python: calls.append(("dependencies", root, python)),
        raising=False,
    )
    monkeypatch.setattr(
        manage, "apply_database_upgrade", lambda *args: calls.append("migrate")
    )
    monkeypatch.setattr(
        manage, "build_frontend", lambda *args, **kwargs: calls.append("build")
    )
    monkeypatch.setattr(
        manage, "install_frontend", lambda: calls.append("npm") or "npm"
    )
    monkeypatch.setattr(
        manage, "supervise", lambda *args, **kwargs: calls.append("serve") or 0
    )
    return tmp_path, calls


@pytest.mark.parametrize("mode", ["production", "development"])
def test_prepared_launch_satisfies_backend_requirements_under_mode_lock_before_effects(
    prepared_launch, mode
):
    root, calls = prepared_launch
    env = {"DATABASE_URL_PRODUCTION": "postgresql://localhost/synthetic"}
    assert (
        manage.launch_prepared_application(
            launch_args(mode=mode),
            env,
            {},
            sys.executable,
            12345,
            "b" * 40,
            FakeLease(),
        )
        == 0
    )
    assert calls[:3] == [
        ("lock", mode),
        ("dependencies", root, sys.executable),
        "clear",
    ]
    assert calls[3:] == (
        ["migrate", "build", "serve"] if mode == "production" else ["npm", "serve"]
    )


def test_dependency_failure_never_migrates_builds_serves_or_publishes_record(
    prepared_launch, monkeypatch
):
    root, calls = prepared_launch

    def fail(*args):
        calls.append("dependency failure")
        raise RuntimeError("synthetic package failure")

    monkeypatch.setattr(manage, "ensure_backend_dependencies", fail)
    with pytest.raises(StartupError, match="DEPENDENCIES"):
        manage.launch_prepared_application(
            launch_args(),
            {"DATABASE_URL_PRODUCTION": "postgresql://localhost/synthetic"},
            {},
            sys.executable,
            12345,
            "b" * 40,
            FakeLease(),
        )
    assert calls == [("lock", "production"), "dependency failure"]
    assert not (root / ".runtime/production.json").exists()


def test_detached_parent_never_synchronizes_dependencies(prepared_launch, monkeypatch):
    _, calls = prepared_launch
    monkeypatch.setattr(manage.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        manage.subprocess,
        "Popen",
        lambda *args, **kwargs: SimpleNamespace(pid=123, poll=lambda: None),
    )
    assert (
        manage.launch_prepared_application(
            launch_args(detach=True),
            {},
            {},
            sys.executable,
            12345,
            "b" * 40,
            FakeLease(),
        )
        == 0
    )
    assert calls == []


@pytest.mark.parametrize("control", ["status", "stop"])
def test_control_commands_do_not_synchronize_dependencies(monkeypatch, control):
    monkeypatch.setattr(manage, "control_instance", lambda *args, **kwargs: 7)
    monkeypatch.setattr(
        manage,
        "ensure_backend_dependencies",
        lambda *args: pytest.fail("control command must not install"),
        raising=False,
    )
    args = SimpleNamespace(
        mode="production", status=control == "status", stop=control == "stop"
    )
    assert manage.run_application(args) == 7


@pytest.mark.parametrize("refresh", [False, True])
def test_setup_reuses_shared_backend_synchronizer(tmp_path, monkeypatch, refresh):
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("temporary interpreter marker")
    (tmp_path / "requirements.txt").write_text("boto3[crt]>=1.41,<2\n")
    calls = []
    monkeypatch.setattr(setup, "ROOT", tmp_path)
    monkeypatch.setattr(
        setup.sys, "argv", ["setup", *(["--refresh"] if refresh else [])]
    )
    monkeypatch.setattr(setup, "instance_lock", lambda *args: nullcontext())
    monkeypatch.setattr(
        setup.subprocess, "check_output", lambda *args, **kwargs: "3.13\n"
    )
    monkeypatch.setattr(
        setup.subprocess, "run", lambda *args, **kwargs: calls.append("legacy pip")
    )
    monkeypatch.setattr(
        setup, "install_frontend", lambda **kwargs: calls.append("frontend")
    )
    monkeypatch.setattr(
        setup,
        "ensure_backend_dependencies",
        lambda root, selected, *, upgrade=False: calls.append(
            (root, selected, upgrade)
        ),
        raising=False,
    )
    setup.main()
    assert calls == [(tmp_path, str(python), refresh), "frontend"]
