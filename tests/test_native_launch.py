from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import pytest

from scripts import manage
from scripts.shared import processes
from scripts.shared.local_postgres import temporary_postgres
from scripts.shared.processes import instance_lock, supervise


def test_temporary_cluster_is_ready_and_removed_even_when_body_fails():
    data_directory = None
    with pytest.raises(RuntimeError, match="intentional test failure"):
        with temporary_postgres() as url:
            parsed = urlsplit(url)
            admin_url = urlunsplit(parsed._replace(path="/postgres"))
            with psycopg2.connect(admin_url, connect_timeout=2) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW data_directory")
                    data_directory = Path(cursor.fetchone()[0])
                    assert data_directory.is_dir()
                    cursor.execute("SELECT current_user")
                    assert cursor.fetchone()[0] == "agent_smith_test"
            raise RuntimeError("intentional test failure")
    assert data_directory is not None and not data_directory.parent.exists()
    with pytest.raises(psycopg2.OperationalError):
        psycopg2.connect(admin_url, connect_timeout=2)


@pytest.mark.parametrize(("termination", "expected_status", "expected_detail"), [
    ("raise SystemExit(42)", 42, "returncode=42"),
    ("os.kill(os.getpid(), signal.SIGTERM)", 143, "returncode=-15, signal=SIGTERM (15)"),
])
def test_managed_child_failure_stops_and_reaps_its_sibling(tmp_path, capsys, termination, expected_status, expected_detail):
    pid_file = tmp_path / "child.pid"
    child = [sys.executable, "-c", f"import os,time; from pathlib import Path; Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"]
    failure_file = tmp_path / "failure.pid"
    failure = [sys.executable, "-c",
               f"import os,signal,time; from pathlib import Path; "
               f"Path({str(failure_file)!r}).write_text(str(os.getpid())); "
               f"time.sleep(0.5); {termination}", "private-command-argument"]
    result = supervise([(child, tmp_path), (failure, tmp_path)], dict(os.environ))
    assert result == expected_status
    diagnostic = capsys.readouterr().err
    assert f"frontend child (pid={int(failure_file.read_text())})" in diagnostic
    assert f"{expected_detail}, launcher_exit={expected_status}" in diagnostic
    assert "private-command-argument" not in diagnostic
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


@pytest.mark.parametrize(("override", "expected"), [(None, "1"), ("", ""), ("1", "1")])
def test_native_signal_reports_segfault_and_preserves_faulthandler_override(tmp_path, monkeypatch, capsys, override, expected):
    env = {"PATH": "/bin"}
    if override is not None:
        env["PYTHONFAULTHANDLER"] = override
    original_env = dict(env)
    captured = []

    def start_child(command, **kwargs):
        captured.append(kwargs["env"])
        return SimpleNamespace(pid=12345, poll=lambda: -11)

    monkeypatch.setattr(processes.subprocess, "Popen", start_child)
    result = supervise([([sys.executable, "private-command-argument"], tmp_path)], env)
    assert result == 139
    assert captured[0]["PYTHONFAULTHANDLER"] == expected
    assert env == original_env
    diagnostic = capsys.readouterr().err
    assert "API child (pid=12345)" in diagnostic
    assert "returncode=-11, signal=SIGSEGV (11), launcher_exit=139" in diagnostic
    assert "private-command-argument" not in diagnostic


def test_api_child_has_faulthandler_enabled(tmp_path):
    result_file = tmp_path / "faulthandler.json"
    command = [sys.executable, "-c",
               f"import faulthandler,json; from pathlib import Path; "
               f"Path({str(result_file)!r}).write_text(json.dumps(faulthandler.is_enabled()))"]
    env = dict(os.environ)
    env.pop("PYTHONFAULTHANDLER", None)
    assert supervise([(command, tmp_path)], env) == 1
    assert json.loads(result_file.read_text()) is True


def test_intentional_supervisor_shutdown_does_not_report_child_failure(tmp_path, monkeypatch, capsys):
    def poll_during_shutdown():
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return -signal.SIGTERM

    child = SimpleNamespace(pid=12345, poll=poll_during_shutdown)
    stopped = []
    monkeypatch.setattr(processes.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(processes, "stop_process", stopped.append)
    assert supervise([([sys.executable, "-c", "pass"], tmp_path)], {}) == 0
    assert stopped == [child]
    assert not capsys.readouterr().err


def test_unchanged_frontend_skips_build_and_changed_source_rebuilds(tmp_path, monkeypatch):
    client = tmp_path / "client"
    (client / "src").mkdir(parents=True)
    (client / "package.json").write_text("{}")
    (client / "index.html").write_text("source html")
    source = client / "src/App.tsx"
    source.write_text("first source")
    monkeypatch.setattr(manage, "CLIENT", client)
    installs, builds = [], []
    monkeypatch.setattr(manage, "install_frontend", lambda: installs.append(True) or "npm")

    def build(*args, **kwargs):
        builds.append(True)
        (client / "dist").mkdir(exist_ok=True)
        (client / "dist/index.html").write_text("built html")

    monkeypatch.setattr(manage, "checked", build)
    manage.build_frontend({})
    manage.build_frontend({})
    assert len(builds) == len(installs) == 1
    source.write_text("changed source")
    manage.build_frontend({})
    assert len(builds) == len(installs) == 2


def test_changing_sources_during_build_never_stamps_success(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    source = tmp_path / "index.html"
    source.write_text("source")
    monkeypatch.setattr(manage, "CLIENT", tmp_path)
    monkeypatch.setattr(manage, "install_frontend", lambda: "npm")
    monkeypatch.setattr(manage, "checked", lambda *args, **kwargs: source.write_text("changed mid build"))
    with pytest.raises(RuntimeError, match="sources changed"):
        manage.build_frontend({})
    assert not (tmp_path / "dist/.agent-smith-source-hash").exists()


def test_frontend_processes_do_not_inherit_application_credentials():
    result = manage.frontend_environment({
        "PATH": "/bin", "DASHBOARD_PORT": "7655", "VITE_PUBLIC_LABEL": "dev",
        "DATABASE_URL_PRODUCTION": "secret", "ANTHROPIC_API_KEY": "secret",
    })
    assert result == {"PATH": "/bin", "DASHBOARD_PORT": "7655", "VITE_PUBLIC_LABEL": "dev"}


def test_running_instance_blocks_dependency_changes_and_duplicate_launch(tmp_path):
    with instance_lock(tmp_path, "production"):
        with pytest.raises(RuntimeError, match="already running"):
            with instance_lock(tmp_path, "production"):
                pytest.fail("Production lock must not be acquired twice")
    with instance_lock(tmp_path, "production"):
        pass


def _start_fake_launcher(root: Path, token: str) -> subprocess.Popen:
    """A process that holds production's lock and record the way a real launcher does."""
    ready = root / "ready"
    code = f"""
import json, os, signal, sys, time
from pathlib import Path
sys.path.insert(0, {str(Path(manage.ROOT))!r})
from scripts.shared.processes import instance_lock
root = Path({str(root)!r})
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
with instance_lock(root, "production"):
    record = root / ".runtime/production.json"
    record.write_text(json.dumps({{"pid": os.getpid(), "token": {token!r}}}))
    try:
        (root / "ready").write_text("1")
        time.sleep(60)
    finally:
        record.unlink(missing_ok=True)
"""
    # The launcher identity check matches manage.py's path and the launch token in the command line.
    process = subprocess.Popen([sys.executable, "-c", code, str(Path(manage.__file__).resolve()), "--launch-token", token])
    deadline = time.monotonic() + 10
    while not ready.exists():
        assert process.poll() is None and time.monotonic() < deadline, "fake launcher never became ready"
        time.sleep(0.05)
    return process


def test_relaunch_stops_running_instance_and_waits_for_its_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    launcher = _start_fake_launcher(tmp_path, "token-1")
    try:
        assert manage.running_instance("production") == launcher.pid
        manage.replace_running_instance("production")
        with instance_lock(tmp_path, "production"):
            pass
        assert launcher.wait(timeout=5) == 0
        assert not (tmp_path / ".runtime/production.json").exists()
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.wait()


def test_relaunch_stops_a_launcher_suspended_in_its_terminal(tmp_path, monkeypatch):
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    launcher = _start_fake_launcher(tmp_path, "token-suspended")
    try:
        os.kill(launcher.pid, signal.SIGSTOP)
        manage.replace_running_instance("production")
        assert launcher.wait(timeout=5) == 0
        assert not (tmp_path / ".runtime/production.json").exists()
    finally:
        if launcher.poll() is None:
            launcher.kill()
            launcher.wait()


def test_record_of_a_dead_launcher_is_discarded_instead_of_blocking_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    record = tmp_path / ".runtime/production.json"
    record.parent.mkdir()
    record.write_text(json.dumps({"pid": finished.pid, "token": "gone"}))
    assert manage.running_instance("production") is None
    assert not record.exists()


def test_record_pointing_at_an_unrelated_process_is_never_signalled(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    record = tmp_path / ".runtime/production.json"
    record.parent.mkdir()
    record.write_text(json.dumps({"pid": os.getpid(), "token": "not-this-process"}))
    with pytest.raises(RuntimeError, match="unrelated process"):
        manage.replace_running_instance("production")
    assert record.exists()


def test_only_the_user_facing_launch_replaces_a_running_instance(monkeypatch):
    class Launched(Exception):
        pass

    def launch(*args, **kwargs):
        raise Launched

    replaced = []
    monkeypatch.setattr(manage, "selected_environment", lambda mode: {})
    monkeypatch.setattr(manage, "replace_running_instance", replaced.append)
    monkeypatch.setattr(manage.os, "execve", launch)
    monkeypatch.setattr(manage, "instance_lock", launch)
    args = argparse.Namespace(mode="production", stop=False, status=False, detach=False, rebuild=False, launch_token=None)
    with pytest.raises(Launched):
        manage.run_application(args)
    assert replaced == ["production"]
    with pytest.raises(Launched):
        manage.run_application(argparse.Namespace(**{**vars(args), "launch_token": "child"}))
    assert replaced == ["production"]
