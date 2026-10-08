from __future__ import annotations

import os
from pathlib import Path
import sys
from urllib.parse import urlsplit, urlunsplit

import psycopg2
import pytest

from scripts import manage
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


def test_managed_child_failure_stops_and_reaps_its_sibling(tmp_path):
    pid_file = tmp_path / "child.pid"
    child = [sys.executable, "-c", f"import os,time; from pathlib import Path; Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"]
    failure = [sys.executable, "-c", "import time; time.sleep(0.5); raise SystemExit(42)"]
    result = supervise([(child, tmp_path), (failure, tmp_path)], dict(os.environ))
    assert result == 42
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


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
