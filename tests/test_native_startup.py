from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.shared.native_startup import Checkout, StartupError
from scripts.shared.native_startup import StartupLease, prepare_startup, probe_database
from scripts.shared.processes import instance_lock
from scripts import manage


@pytest.fixture(autouse=True)
def isolate_backend_dependency_installation(monkeypatch):
    monkeypatch.setattr(manage, "ensure_backend_dependencies", lambda *args: False)


class FakeCommands:
    def __init__(self, root, *, branch="main", dirty="", ancestor=True):
        self.root = root
        self.branch = branch
        self.dirty = dirty
        self.ancestor = ancestor
        self.head = "a" * 40
        self.target = "b" * 40
        self.calls = []

    def __call__(self, arguments, **kwargs):
        self.calls.append(arguments)
        code, output = 0, ""
        if arguments[0] != "git":
            output = (
                "3.13"
                if arguments[0] == sys.executable
                and "sys.version_info" in arguments[-1]
                else "v22.12.0"
            )
        elif arguments[1:3] == ["rev-parse", "--show-toplevel"]:
            output = str(self.root)
        elif arguments[1] == "branch":
            output = self.branch
        elif arguments[1] == "status":
            output = self.dirty
        elif arguments[1] == "rev-parse":
            output = (
                self.target
                if arguments[-1].startswith("refs/remotes/origin/main")
                else self.head
            )
        elif arguments[1] == "merge-base":
            code = 0 if self.ancestor else 1
        elif arguments[1] == "merge":
            self.head = arguments[-1]
        return SimpleNamespace(returncode=code, stdout=output, stderr="")


def test_git_preflight_pins_fetched_revision_without_changing_checkout(tmp_path):
    commands = FakeCommands(tmp_path)
    checkout = Checkout(tmp_path, run=commands, which=lambda name: name)
    snapshot = checkout.preflight(sys.executable)
    assert (snapshot.head, snapshot.target) == ("a" * 40, "b" * 40)
    assert commands.head == snapshot.head
    assert [
        "git",
        "fetch",
        "--no-tags",
        "origin",
        "refs/heads/main:refs/remotes/origin/main",
    ] in commands.calls
    assert not any(command[1] == "merge" for command in commands.calls)
    checkout.fast_forward(snapshot)
    assert commands.head == snapshot.target
    assert ["git", "merge", "--ff-only", snapshot.target] in commands.calls


@pytest.mark.parametrize(
    "options",
    [
        {"branch": "feature/work"},
        {"branch": ""},
        {"dirty": "?? local.txt"},
        {"ancestor": False},
    ],
)
def test_unsafe_checkout_fails_before_any_worktree_update(tmp_path, options):
    commands = FakeCommands(tmp_path, **options)
    checkout = Checkout(tmp_path, run=commands, which=lambda name: name)
    with pytest.raises(StartupError, match="PREFLIGHT"):
        checkout.preflight(sys.executable)
    assert not any(command[1] == "merge" for command in commands.calls)


def test_missing_tool_fails_before_fetch(tmp_path):
    commands = FakeCommands(tmp_path)
    checkout = Checkout(
        tmp_path, run=commands, which=lambda name: None if name == "npm" else name
    )
    with pytest.raises(StartupError, match="npm is missing"):
        checkout.preflight(sys.executable)
    assert commands.calls == []


def test_update_rejects_checkout_drift(tmp_path):
    commands = FakeCommands(tmp_path)
    checkout = Checkout(tmp_path, run=commands, which=lambda name: name)
    snapshot = checkout.preflight(sys.executable)
    commands.head = "c" * 40
    with pytest.raises(StartupError, match="checkout changed"):
        checkout.fast_forward(snapshot)
    assert not any(command[1] == "merge" for command in commands.calls)


def test_rerun_after_an_update_failure_accepts_the_already_updated_clean_head(tmp_path):
    commands = FakeCommands(tmp_path)
    checkout = Checkout(tmp_path, run=commands, which=lambda name: name)
    snapshot = checkout.preflight(sys.executable)
    commands.head = snapshot.target
    with pytest.raises(StartupError, match="checkout changed"):
        checkout.fast_forward(snapshot)
    retry = checkout.preflight(sys.executable)
    assert retry.head == retry.target
    checkout.fast_forward(retry)
    assert commands.head == snapshot.target


def test_git_commands_cannot_be_redirected_by_inherited_environment(tmp_path):
    commands = FakeCommands(tmp_path)
    checkout = Checkout(
        tmp_path,
        run=commands,
        which=lambda name: name,
        inherited={
            "GIT_DIR": "/private/other",
            "GIT_WORK_TREE": str(tmp_path),
            "GIT_CONFIG_COUNT": "1",
            "PATH": "/bin",
            "CUSTOM_VALUE": "kept",
        },
    )
    checkout.preflight(sys.executable)
    assert checkout.env == {
        "PATH": "/bin",
        "CUSTOM_VALUE": "kept",
        "GIT_TERMINAL_PROMPT": "0",
    }


def test_preparation_checks_everything_before_stop_and_updates_only_after_port_is_clear(
    tmp_path,
):
    calls = []
    commands = FakeCommands(tmp_path)
    checkout = Checkout(tmp_path, run=commands, which=lambda name: name)
    snapshot = object()
    original_update = checkout.fast_forward

    def update(value):
        calls.append("update")
        original_update(value)

    checkout.fast_forward = update
    result = prepare_startup(
        tmp_path,
        sys.executable,
        12345,
        {},
        checkout=checkout,
        validate_instances=lambda: calls.append("instances"),
        validate_database=lambda: calls.append("database"),
        inspect_port=lambda port: calls.append("snapshot") or snapshot,
        stop_managed=lambda: calls.append("managed_stop"),
        terminate=lambda captured: calls.append(("terminate", captured)),
        clear_port=lambda port: calls.append("clear"),
    )
    assert calls == [
        "instances",
        "database",
        "snapshot",
        "instances",
        "managed_stop",
        ("terminate", snapshot),
        "clear",
        "update",
    ]
    assert result == "b" * 40


def test_preparation_does_not_stop_anything_when_a_preflight_fails(tmp_path):
    calls = []
    checkout = Checkout(
        tmp_path,
        run=FakeCommands(tmp_path, branch="feature/work"),
        which=lambda name: name,
    )
    with pytest.raises(StartupError, match="main"):
        prepare_startup(
            tmp_path,
            sys.executable,
            12345,
            {},
            checkout=checkout,
            validate_instances=lambda: None,
            validate_database=lambda: None,
            inspect_port=lambda port: calls.append("snapshot"),
            stop_managed=lambda: calls.append("stop"),
            terminate=lambda captured: calls.append("terminate"),
            clear_port=lambda port: calls.append("clear"),
        )
    assert calls == []


def test_failed_database_authentication_keeps_existing_service_untouched(tmp_path):
    calls = []
    checkout = Checkout(tmp_path, run=FakeCommands(tmp_path), which=lambda name: name)

    def denied_database():
        probe_database(
            sys.executable,
            {"DATABASE_URL_PRODUCTION": "private"},
            run=lambda *args, **kwargs: SimpleNamespace(
                returncode=1, stdout="", stderr="private credentials"
            ),
        )

    with pytest.raises(StartupError, match="database probe failed") as error:
        prepare_startup(
            tmp_path,
            sys.executable,
            12345,
            {},
            checkout=checkout,
            validate_instances=lambda: None,
            validate_database=denied_database,
            inspect_port=lambda port: calls.append("snapshot"),
            stop_managed=lambda: calls.append("stop"),
            terminate=lambda captured: calls.append("terminate"),
            clear_port=lambda port: calls.append("clear"),
        )
    assert calls == []
    assert "private" not in str(error.value)


def test_inherited_lease_validates_identity_and_closes_idempotently(tmp_path):
    with instance_lock(tmp_path, "startup", inherit=True) as descriptor:
        inherited = os.dup(descriptor)
        lease = StartupLease(tmp_path, inherited)
        assert lease.fileno() == inherited
        assert os.get_inheritable(inherited)
        lease.close()
        lease.close()
        with pytest.raises(OSError):
            os.fstat(inherited)
        os.fstat(descriptor)
    with pytest.raises(StartupError, match="handoff"):
        StartupLease(tmp_path, -1)


def test_detached_child_keeps_startup_lock_after_the_parent_closes_its_copy(
    tmp_path, monkeypatch, capsys
):
    root = Path(manage.__file__).resolve().parent.parent
    code = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(root)!r})
from scripts.shared.native_startup import StartupLease
root = Path(sys.argv[1])
lease = StartupLease(root, int(sys.argv[2]))
(root / 'ready').write_text('1')
sys.stdin.read(1)
lease.close()
"""
    process = None
    try:
        with instance_lock(tmp_path, "startup", inherit=True) as descriptor:
            process = subprocess.Popen(
                [sys.executable, "-c", code, str(tmp_path), str(descriptor)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                pass_fds=(descriptor,),
                start_new_session=True,
            )
            deadline = time.monotonic() + 5
            while not (tmp_path / "ready").exists():
                assert process.poll() is None and time.monotonic() < deadline, (
                    "startup handoff did not become ready"
                )
                time.sleep(0.01)
        with pytest.raises(RuntimeError, match="already running"):
            with instance_lock(tmp_path, "startup"):
                pytest.fail("the detached child still owns preparation")
        monkeypatch.setattr(manage, "ROOT", tmp_path)
        monkeypatch.setattr(
            manage,
            "stop_instance",
            lambda *args: pytest.fail(
                "preparation must not receive extra stop signals"
            ),
        )
        assert manage.control_instance("production") == 0
        assert "Startup preparing in this checkout" in capsys.readouterr().out
        with pytest.raises(RuntimeError, match="no stop signal was sent"):
            manage.control_instance("production", stop=True)
        process.communicate("release", timeout=5)
        assert process.returncode == 0
        with instance_lock(tmp_path, "startup"):
            pass
        assert manage.control_instance("production") == 0
        assert "production is not running" in capsys.readouterr().out
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=5)


def launch_args(**overrides):
    return SimpleNamespace(
        **{
            "mode": "production",
            "stop": False,
            "status": False,
            "detach": False,
            "rebuild": False,
            "launch_token": "prepared",
            "startup_revision": "b" * 40,
            "startup_lock_fd": 99,
            **overrides,
        }
    )


def test_control_paths_do_not_prepare_or_validate_configuration(monkeypatch):
    monkeypatch.setattr(manage, "control_instance", lambda mode, stop: 7)
    monkeypatch.setattr(
        manage,
        "selected_environment",
        lambda mode: pytest.fail("controls must bypass startup"),
    )
    assert (
        manage.run_application(
            SimpleNamespace(mode="production", stop=True, status=False)
        )
        == 7
    )
    assert (
        manage.run_application(
            SimpleNamespace(mode="development", stop=False, status=True)
        )
        == 7
    )


def test_stop_refuses_to_race_preparation_even_when_an_old_service_record_exists(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(manage, "running_instance", lambda mode: 123)
    monkeypatch.setattr(
        manage,
        "stop_instance",
        lambda *args: pytest.fail("no signal during preparation"),
    )
    with instance_lock(tmp_path, "startup"):
        with pytest.raises(RuntimeError, match="no stop signal was sent"):
            manage.control_instance("production", stop=True)


def test_reexecution_preserves_original_environment_and_flags(tmp_path, monkeypatch):
    class Reexecuted(Exception):
        pass

    captured = {}
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(
        manage,
        "selected_environment",
        lambda mode: {"DASHBOARD_PORT": "12345", "OLD_DEFAULT": "must_not_be_frozen"},
    )
    monkeypatch.setattr(manage, "python_executable", lambda: sys.executable)
    monkeypatch.setattr(manage, "prepare_startup", lambda *args, **kwargs: "b" * 40)
    monkeypatch.setenv("EXPLICIT_STARTUP_VALUE", "preserved")

    def execute(executable, arguments, env):
        captured.update(executable=executable, arguments=arguments, env=env)
        descriptor = int(arguments[arguments.index("--startup-lock-fd") + 1])
        assert os.get_inheritable(descriptor)
        raise Reexecuted

    monkeypatch.setattr(manage.os, "execve", execute)
    args = SimpleNamespace(
        mode="dev",
        stop=False,
        status=False,
        detach=True,
        rebuild=True,
        launch_token=None,
    )
    with pytest.raises(Reexecuted):
        manage.run_application(args)
    assert captured["env"]["EXPLICIT_STARTUP_VALUE"] == "preserved"
    assert "OLD_DEFAULT" not in captured["env"]
    assert captured["executable"] == sys.executable
    assert "--rebuild" in captured["arguments"] and "--detach" in captured["arguments"]
    assert (
        captured["arguments"][captured["arguments"].index("--startup-revision") + 1]
        == "b" * 40
    )


class FakeLease:
    def __init__(self):
        self.closed = False

    def fileno(self):
        return 99

    def close(self):
        self.closed = True


@contextmanager
def fake_lock(*args, **kwargs):
    yield 99


def test_production_migrates_once_under_lock_before_build_and_supervision(
    tmp_path, monkeypatch
):
    calls = []
    lease = FakeLease()
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(manage, "instance_lock", fake_lock)
    monkeypatch.setattr(manage, "assert_port_clear", lambda port: calls.append("clear"))
    monkeypatch.setattr(
        manage,
        "apply_database_upgrade",
        lambda env, name: calls.append(("migrate", name)),
    )
    monkeypatch.setattr(
        manage, "build_frontend", lambda env, force: calls.append(("build", force))
    )

    def serve(*args, **kwargs):
        assert lease.closed
        calls.append("serve")
        return 0

    monkeypatch.setattr(manage, "supervise", serve)
    env = {"DATABASE_URL_PRODUCTION": "postgresql://localhost/synthetic"}
    assert (
        manage.launch_prepared_application(
            launch_args(), env, {}, sys.executable, 12345, "b" * 40, lease
        )
        == 0
    )
    assert calls == ["clear", ("migrate", "synthetic"), ("build", False), "serve"]
    assert not (tmp_path / ".runtime/production.json").exists()


def test_detached_parent_only_hands_off_and_does_not_migrate(tmp_path, monkeypatch):
    captured = {}
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(
        manage,
        "apply_database_upgrade",
        lambda *args: pytest.fail("parent must not migrate"),
    )
    monkeypatch.setattr(manage.time, "sleep", lambda _: None)

    def spawn(command, **kwargs):
        captured.update(command=command, **kwargs)
        return SimpleNamespace(pid=123, poll=lambda: None)

    monkeypatch.setattr(manage.subprocess, "Popen", spawn)
    args = SimpleNamespace(**{**vars(launch_args()), "detach": True, "rebuild": True})
    assert (
        manage.launch_prepared_application(
            args,
            {"OLD_DEFAULT": "ignored"},
            {"ORIGINAL": "kept"},
            sys.executable,
            12345,
            "b" * 40,
            FakeLease(),
        )
        == 0
    )
    assert captured["env"] == {"ORIGINAL": "kept"}
    assert captured["pass_fds"] == (99,)
    assert "--detach" not in captured["command"] and "--rebuild" in captured["command"]


def test_migration_failure_never_builds_or_starts_the_server(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(manage, "instance_lock", fake_lock)
    monkeypatch.setattr(manage, "assert_port_clear", lambda port: None)
    monkeypatch.setattr(
        manage,
        "apply_database_upgrade",
        lambda *args: (_ for _ in ()).throw(RuntimeError("failed")),
    )
    monkeypatch.setattr(
        manage,
        "build_frontend",
        lambda *args, **kwargs: pytest.fail("migration failed"),
    )
    monkeypatch.setattr(
        manage, "supervise", lambda *args, **kwargs: pytest.fail("migration failed")
    )
    with pytest.raises(StartupError, match="MIGRATING"):
        manage.launch_prepared_application(
            launch_args(),
            {"DATABASE_URL_PRODUCTION": "postgresql://localhost/synthetic"},
            {},
            sys.executable,
            12345,
            "b" * 40,
            FakeLease(),
        )


@pytest.mark.parametrize("failure", ["migrate", "build"])
def test_failed_preparation_can_be_rerun_without_publishing_a_partial_process_record(
    tmp_path, monkeypatch, failure
):
    calls = []
    first = True
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(manage, "instance_lock", fake_lock)
    monkeypatch.setattr(manage, "assert_port_clear", lambda port: None)

    def operation(name):
        nonlocal first
        calls.append(name)
        if name == failure and first:
            first = False
            raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(
        manage, "apply_database_upgrade", lambda *args: operation("migrate")
    )
    monkeypatch.setattr(
        manage, "build_frontend", lambda *args, **kwargs: operation("build")
    )
    monkeypatch.setattr(
        manage, "supervise", lambda *args, **kwargs: calls.append("serve") or 0
    )
    env = {"DATABASE_URL_PRODUCTION": "postgresql://localhost/synthetic"}
    with pytest.raises(StartupError):
        manage.launch_prepared_application(
            launch_args(), env, {}, sys.executable, 12345, "b" * 40, FakeLease()
        )
    assert not (tmp_path / ".runtime/production.json").exists()
    assert (
        manage.launch_prepared_application(
            launch_args(), env, {}, sys.executable, 12345, "b" * 40, FakeLease()
        )
        == 0
    )
    assert calls.count("serve") == 1
    assert calls[-3:] == ["migrate", "build", "serve"]


def test_development_keeps_hmr_and_existing_application_migration_flow(
    tmp_path, monkeypatch
):
    commands = []
    monkeypatch.setattr(manage, "ROOT", tmp_path)
    monkeypatch.setattr(manage, "instance_lock", fake_lock)
    monkeypatch.setattr(manage, "assert_port_clear", lambda port: None)
    monkeypatch.setattr(
        manage,
        "apply_database_upgrade",
        lambda *args: pytest.fail("dev migrations belong to app startup"),
    )
    monkeypatch.setattr(
        manage, "build_frontend", lambda *args, **kwargs: pytest.fail("dev uses HMR")
    )
    monkeypatch.setattr(manage, "install_frontend", lambda: "npm")
    monkeypatch.setattr(
        manage, "supervise", lambda value, *args, **kwargs: commands.extend(value) or 0
    )
    assert (
        manage.launch_prepared_application(
            launch_args(mode="dev"),
            {},
            {},
            sys.executable,
            12345,
            "b" * 40,
            FakeLease(),
        )
        == 0
    )
    assert "--reload" in commands[0][0]
    assert commands[1][0] == ["npm", "run", "dev", "--", "--strictPort"]


def test_other_active_mode_is_rejected_before_preparation(monkeypatch):
    monkeypatch.setattr(
        manage, "running_instance", lambda mode: 123 if mode == "development" else None
    )
    monkeypatch.setattr(manage, "instance_lock", fake_lock)
    with pytest.raises(StartupError, match="development is active"):
        manage.validate_startup_instances("production")


def test_disposable_remote_fast_forward_reexecutes_new_source_with_original_environment(
    tmp_path,
):
    origin, producer, checkout = (
        tmp_path / name for name in ("origin.git", "producer", "checkout")
    )
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env["GIT_TERMINAL_PROMPT"] = "0"

    def git(directory, *arguments):
        subprocess.run(
            ["git", *arguments],
            cwd=directory,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )

    git(tmp_path, "init", "--bare", str(origin))
    git(tmp_path, "init", "-b", "main", str(producer))
    git(producer, "config", "user.name", "Startup Test")
    git(producer, "config", "user.email", "startup@example.invalid")
    (producer / ".gitignore").write_text(".runtime/\n")
    marker = producer / "launcher.py"
    marker.write_text("print('old')\n")
    git(producer, "add", ".")
    git(producer, "-c", "commit.gpgsign=false", "commit", "-m", "initial")
    git(producer, "remote", "add", "origin", str(origin))
    git(producer, "push", "origin", "main")
    git(tmp_path, "clone", "--branch", "main", str(origin), str(checkout))
    marker.write_text(
        "import json,os; print(json.dumps({'marker':'new','explicit':os.environ.get('EXPLICIT_STARTUP_VALUE'),'old_default':os.environ.get('OLD_DEFAULT')}))\n"
    )
    git(producer, "add", ".")
    git(producer, "-c", "commit.gpgsign=false", "commit", "-m", "updated launcher")
    git(producer, "push", "origin", "main")
    root = Path(manage.__file__).resolve().parent.parent
    code = f"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, {str(root)!r})
from scripts import manage
from scripts.shared.native_startup import Checkout, prepare_startup
manage.ROOT = Path({str(checkout)!r})
manage.__file__ = str(manage.ROOT / "launcher.py")
manage.python_executable = lambda: sys.executable
manage.selected_environment = lambda mode: {{"DASHBOARD_PORT":"12345","OLD_DEFAULT":"must_not_be_frozen"}}
manage.prepare_startup = lambda root, python, port, inherited, **kwargs: prepare_startup(
    root, python, port, inherited, checkout=Checkout(root, inherited=inherited),
    validate_instances=lambda:None, validate_database=lambda:None, stop_managed=lambda:None,
    inspect_port=lambda port:object(), terminate=lambda snapshot:None, clear_port=lambda port:None)
manage.run_application(SimpleNamespace(mode="production",stop=False,status=False,detach=False,rebuild=False,launch_token=None))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**env, "EXPLICIT_STARTUP_VALUE": "preserved"},
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    value = json.loads(result.stdout.splitlines()[-1])
    assert value == {"marker": "new", "explicit": "preserved", "old_default": None}


def shell_fixture(tmp_path):
    root = tmp_path / "checkout with spaces"
    (root / "scripts").mkdir(parents=True)
    original = Path(__file__).resolve().parents[1] / "run.sh"
    (root / "run.sh").write_text(original.read_text())
    (root / "scripts/manage.py").write_text(
        "import json,os,sys; print(json.dumps({'argv':sys.argv[1:],'activated':os.environ.get('TEST_ACTIVATED'),'python':os.environ.get('AGENT_SMITH_PYTHON')}))"
    )
    env = {
        **os.environ,
        "LAUNCH_PYTHON": sys.executable,
        "AGENT_SMITH_PYTHON": sys.executable,
    }
    return root, env


@pytest.mark.parametrize("flag", ["--help", "-h", "--status", "--stop"])
def test_control_flags_bypass_activation(tmp_path, flag):
    root, env = shell_fixture(tmp_path)
    env["AGENT_SMITH_VENV_ACTIVATE"] = str(root / "missing")
    result = subprocess.run(
        ["bash", str(root / "run.sh"), "dev", flag],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["argv"] == ["run", "dev", flag]
    assert json.loads(result.stdout)["activated"] is None


def test_launch_sources_configured_environment_and_preserves_flags(tmp_path):
    root, env = shell_fixture(tmp_path)
    activation = root / "custom environment" / "activate"
    activation.parent.mkdir()
    activation.write_text("export TEST_ACTIVATED=1\n")
    env["AGENT_SMITH_VENV_ACTIVATE"] = str(activation)
    result = subprocess.run(
        ["bash", str(root / "run.sh"), "dev", "-d", "-nc"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    value = json.loads(result.stdout)
    assert value == {
        "argv": ["run", "dev", "-d", "-nc"],
        "activated": "1",
        "python": sys.executable,
    }
