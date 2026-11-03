from __future__ import annotations

import os
import ctypes
import errno
from pathlib import Path
import select
import shutil
import signal
import socket
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts.shared import port_processes
from scripts.shared.port_processes import (
    ListenerSnapshot,
    PortProcessError,
    PortProcesses,
    ProcessIdentity,
)
from scripts.shared.processes import InstanceRunningError, instance_lock


PORT = 49152


@pytest.mark.parametrize("inherit", [False, True])
def test_instance_lock_yields_explicit_descriptor_inheritance(tmp_path, inherit):
    with instance_lock(tmp_path, "startup", inherit=inherit) as descriptor:
        assert os.get_inheritable(descriptor) is inherit
        with pytest.raises(InstanceRunningError):
            with instance_lock(tmp_path, "startup"):
                pytest.fail("the held lock was acquired twice")
    with pytest.raises(OSError):
        os.fstat(descriptor)
    with instance_lock(tmp_path, "startup") as descriptor:
        assert not os.get_inheritable(descriptor)


class FakeProcesses:
    def __init__(self):
        self.identities = {101: ProcessIdentity(101, 501, "birth-1", "/bin/worker")}
        self.listeners = {PORT: {101}, 49153: {202}}
        self.signals = []
        self.queries = []
        self.now = 0.0
        self.list_calls = 0
        self.on_list = lambda count: None
        self.on_signal = lambda pid, signum: self.listeners[PORT].discard(pid)
        self.denied = set()
        self.inspector = PortProcesses(
            run=self.run, kill=self.kill, clock=lambda: self.now, sleep=self.sleep,
            which=lambda name: f"/tools/{name}",
            birth_token=lambda pid: self.identities[pid].birth if pid in self.identities else None,
            check_bindable=lambda port: None,
            uid=501,
        )

    def sleep(self, seconds):
        self.now += seconds

    def kill(self, pid, signum):
        if pid in self.denied:
            raise PermissionError("private process arguments")
        self.signals.append((pid, signum))
        if signum:
            self.on_signal(pid, signum)

    def run(self, command, **kwargs):
        self.queries.append(command)
        if Path(command[0]).name == "lsof":
            self.list_calls += 1
            self.on_list(self.list_calls)
            port = int(next(value for value in command if value.startswith("-iTCP:"))[6:])
            pids = self.listeners.get(port, set())
            return SimpleNamespace(returncode=0 if pids else 1,
                                   stdout="".join(f"p{pid}\n" for pid in sorted(pids)), stderr="")
        identity = self.identities.get(int(command[2]))
        return SimpleNamespace(returncode=0 if identity else 1,
                               stdout=f"{identity.uid} {identity.executable}\n" if identity else "", stderr="")

    def nonzero_signals(self):
        return [(pid, signum) for pid, signum in self.signals if signum]


def test_snapshot_and_shutdown_only_target_the_selected_port():
    fake = FakeProcesses()
    snapshot = fake.inspector.snapshot_port(PORT)
    assert snapshot == ListenerSnapshot(PORT, (fake.identities[101],))
    assert fake.nonzero_signals() == []
    fake.inspector.terminate_port_listeners(snapshot)
    fake.inspector.assert_port_clear(PORT)
    assert fake.nonzero_signals() == [(101, signal.SIGTERM)]
    assert fake.listeners[49153] == {202}
    lsof_queries = [query for query in fake.queries if query[0].endswith("lsof")]
    assert all(f"-iTCP:{PORT}" in query and "-sTCP:LISTEN" in query for query in lsof_queries)
    assert all("args=" not in argument for query in fake.queries for argument in query)


@pytest.mark.parametrize("port", [0, 65536, True, "49152", None])
def test_port_validation_precedes_any_tool_or_signal(port):
    fake = FakeProcesses()
    with pytest.raises(ValueError, match="port"):
        fake.inspector.snapshot_port(port)
    assert not fake.queries and not fake.signals


@pytest.mark.parametrize("missing", ["lsof", "ps"])
def test_missing_tool_fails_before_any_signal(missing):
    fake = FakeProcesses()
    fake.inspector.which = lambda name: None if name == missing else f"/tools/{name}"
    with pytest.raises(PortProcessError, match=f"required tool '{missing}'"):
        fake.inspector.snapshot_port(PORT)
    assert not fake.signals


def test_timed_out_tool_fails_before_any_signal_without_echoing_arguments():
    fake = FakeProcesses()

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired("private-command-arguments", kwargs["timeout"])

    fake.inspector.run = timeout
    with pytest.raises(PortProcessError, match="TimeoutExpired") as error:
        fake.inspector.snapshot_port(PORT)
    assert "private" not in str(error.value)
    assert not fake.signals


def test_preflight_checks_every_listener_permission_before_signaling_any():
    fake = FakeProcesses()
    fake.identities[102] = ProcessIdentity(102, 501, "birth-2", "/bin/worker")
    fake.listeners[PORT].add(102)
    fake.denied.add(102)
    with pytest.raises(PortProcessError, match=f"port={PORT}, pid=102, stage=preflight") as error:
        fake.inspector.snapshot_port(PORT)
    assert "private" not in str(error.value)
    assert not fake.nonzero_signals()


def test_foreign_uid_is_never_signaled():
    fake = FakeProcesses()
    fake.identities[101] = ProcessIdentity(101, 502, "birth-1", "/bin/worker")
    with pytest.raises(PortProcessError, match="owned by this user"):
        fake.inspector.snapshot_port(PORT)
    assert not fake.signals


def test_uninspectable_occupied_port_fails_before_any_signal():
    fake = FakeProcesses()
    fake.listeners[PORT].clear()

    def busy(port):
        assert port == PORT
        raise OSError(errno.EADDRINUSE, "private information")

    fake.inspector.check_bindable = busy
    with pytest.raises(PortProcessError, match=f"port={PORT}.*stage=preflight.*PID is not inspectable") as error:
        fake.inspector.snapshot_port(PORT)
    assert "private" not in str(error.value)
    assert not fake.signals


def test_replacement_during_permission_probe_is_not_signaled():
    fake = FakeProcesses()
    snapshot = fake.inspector.snapshot_port(PORT)
    original_kill = fake.inspector.kill
    checks = 0

    def replace_after_permission(pid, signum):
        nonlocal checks
        original_kill(pid, signum)
        if signum == 0:
            checks += 1
            if checks == 2:
                fake.identities[pid] = ProcessIdentity(pid, 501, "reused", "/bin/new")

    fake.inspector.kill = replace_after_permission
    with pytest.raises(PortProcessError, match="identity changed"):
        fake.inspector.terminate_port_listeners(snapshot)
    assert not fake.nonzero_signals()


@pytest.mark.parametrize("change", ["birth", "uid", "executable", "pid"])
def test_replacement_between_preflight_and_term_is_never_signaled(change):
    fake = FakeProcesses()
    snapshot = fake.inspector.snapshot_port(PORT)
    fake.list_calls = 0

    def replace(count):
        if count != 2:
            return
        if change == "pid":
            fake.listeners[PORT] = {303}
            fake.identities[303] = ProcessIdentity(303, 501, "replacement", "/bin/new")
        else:
            values = {"pid": 101, "uid": 501, "birth": "birth-1", "executable": "/bin/worker"}
            values[change] = 502 if change == "uid" else "replacement"
            fake.identities[101] = ProcessIdentity(**values)

    fake.on_list = replace
    with pytest.raises(PortProcessError, match=f"port={PORT}.*stage=TERM"):
        fake.inspector.terminate_port_listeners(snapshot)
    assert not fake.nonzero_signals()


def test_listener_that_stops_listening_is_not_killed_at_another_port():
    fake = FakeProcesses()
    snapshot = fake.inspector.snapshot_port(PORT)
    fake.listeners[PORT].clear()
    fake.listeners[49153].add(101)
    fake.inspector.terminate_port_listeners(snapshot)
    assert not fake.nonzero_signals()
    assert fake.listeners[49153] == {101, 202}


@pytest.mark.parametrize("reuse_pid", [False, True])
def test_replacement_after_term_aborts_before_kill(reuse_pid):
    fake = FakeProcesses()
    snapshot = fake.inspector.snapshot_port(PORT)

    def replace(pid, signum):
        new_pid = pid if reuse_pid else 303
        fake.listeners[PORT] = {new_pid}
        fake.identities[new_pid] = ProcessIdentity(new_pid, 501, "replacement", "/bin/new")

    fake.on_signal = replace
    with pytest.raises(PortProcessError, match="replacement listener|identity changed"):
        fake.inspector.terminate_port_listeners(snapshot)
    assert fake.nonzero_signals() == [(101, signal.SIGTERM)]


def test_stubborn_listener_gets_term_then_kill_and_bounded_failure():
    fake = FakeProcesses()
    snapshot = fake.inspector.snapshot_port(PORT)
    fake.on_signal = lambda pid, signum: None
    with pytest.raises(PortProcessError, match=f"port={PORT}, pid=101, stage=KILL.*bounded shutdown"):
        fake.inspector.terminate_port_listeners(snapshot, term_timeout=0.3, kill_timeout=0.2)
    assert fake.nonzero_signals() == [(101, signal.SIGTERM), (101, signal.SIGKILL)]
    assert fake.now == pytest.approx(0.5)


def test_kill_is_only_used_after_term_timeout():
    fake = FakeProcesses()
    snapshot = fake.inspector.snapshot_port(PORT)
    fake.on_signal = lambda pid, signum: fake.listeners[PORT].discard(pid) if signum == signal.SIGKILL else None
    fake.inspector.terminate_port_listeners(snapshot, term_timeout=0.3)
    assert fake.nonzero_signals() == [(101, signal.SIGTERM), (101, signal.SIGKILL)]
    assert fake.now == pytest.approx(0.3)


def test_tool_error_and_malformed_output_fail_closed_without_exposing_output():
    fake = FakeProcesses()
    fake.inspector.run = lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="private", stderr="secret")
    with pytest.raises(PortProcessError, match="lsof could not inspect") as error:
        fake.inspector.snapshot_port(PORT)
    assert "private" not in str(error.value) and "secret" not in str(error.value)
    fake.inspector.run = lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="invalid\n", stderr="")
    with pytest.raises(PortProcessError, match="invalid listener identity"):
        fake.inspector.snapshot_port(PORT)
    assert not fake.signals


def test_lsof_implicit_file_descriptor_fields_are_accepted():
    fake = FakeProcesses()
    original_run = fake.inspector.run

    def with_file_fields(command, **kwargs):
        result = original_run(command, **kwargs)
        if command[0].endswith("lsof") and result.stdout:
            result.stdout += "f3\nf4\n"
        return result

    fake.inspector.run = with_file_fields
    assert fake.inspector.snapshot_port(PORT).listeners == (fake.identities[101],)


def test_linux_birth_token_parses_names_containing_parentheses(monkeypatch):
    monkeypatch.setattr(port_processes.sys, "platform", "linux")
    fields = ["S"] + ["0"] * 18 + ["123456"]
    monkeypatch.setattr(Path, "read_text", lambda self: "123 (worker (job)) " + " ".join(fields))
    assert port_processes._birth_token(123) == "linux:123456"


@pytest.mark.parametrize("record", ["garbage", "123 (worker) S 0", "124 (worker) " + "0 " * 20])
def test_linux_birth_token_rejects_malformed_or_wrong_pid_records(monkeypatch, record):
    monkeypatch.setattr(port_processes.sys, "platform", "linux")
    monkeypatch.setattr(Path, "read_text", lambda self: record)
    with pytest.raises(ValueError, match="birth record"):
        port_processes._birth_token(123)


def test_linux_birth_token_only_treats_missing_process_as_absent(monkeypatch):
    monkeypatch.setattr(port_processes.sys, "platform", "linux")

    def missing(self):
        raise FileNotFoundError

    monkeypatch.setattr(Path, "read_text", missing)
    assert port_processes._birth_token(123) is None

    def denied(self):
        raise PermissionError

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(PermissionError):
        port_processes._birth_token(123)


def test_darwin_birth_token_preserves_microseconds_and_native_layout(monkeypatch):
    monkeypatch.setattr(port_processes.sys, "platform", "darwin")

    class Query:
        def __call__(self, pid, kind, argument, pointer, size):
            assert (pid, kind, argument, size) == (123, 3, 0, 136)
            pointer._obj.pid = pid
            pointer._obj.start_seconds = 1000
            pointer._obj.start_microseconds = 123456
            return size

    monkeypatch.setattr(port_processes.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(proc_pidinfo=Query()))
    assert port_processes._birth_token(123) == "darwin:1000:123456"


@pytest.mark.parametrize("native_errno, expected", [(errno.ESRCH, None), (errno.EACCES, OSError), (0, OSError)])
def test_darwin_birth_token_only_treats_confirmed_disappearance_as_absent(monkeypatch, native_errno, expected):
    monkeypatch.setattr(port_processes.sys, "platform", "darwin")

    class Query:
        def __call__(self, *args):
            ctypes.set_errno(native_errno)
            return 0

    monkeypatch.setattr(port_processes.ctypes, "CDLL", lambda *args, **kwargs: SimpleNamespace(proc_pidinfo=Query()))
    ctypes.set_errno(errno.ESRCH)
    if expected is None:
        assert port_processes._birth_token(123) is None
    else:
        with pytest.raises(expected):
            port_processes._birth_token(123)


@pytest.mark.skipif(not shutil.which("lsof") or not shutil.which("ps"), reason="native listener inspection tools unavailable")
def test_owned_random_port_http_server_is_stopped_without_other_process_signals():
    code = """
from http.server import HTTPServer, BaseHTTPRequestHandler
server = HTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
print(server.server_port, flush=True)
server.serve_forever()
"""
    child = subprocess.Popen([sys.executable, "-u", "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        ready, _, _ = select.select([child.stdout], [], [], 5)
        assert ready, "owned HTTP server did not announce its random port"
        announcement = child.stdout.readline()
        assert announcement, f"owned HTTP server exited before startup: {child.stderr.read()}"
        port = int(announcement)
        assert port != 7654
        hidden_listener = PortProcesses(run=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""))
        # Hidden default-host ownership must fail before the coordinator stops anything.
        with pytest.raises(PortProcessError, match="listener PID is not inspectable"):
            hidden_listener.snapshot_port(port)
        assert child.poll() is None
        snapshot = port_processes.snapshot_port(port)
        assert [identity.pid for identity in snapshot.listeners] == [child.pid]
        assert snapshot.listeners[0].uid == os.geteuid()
        assert snapshot.listeners[0].birth
        port_processes.terminate_port_listeners(snapshot)
        assert child.wait(timeout=3) == -signal.SIGTERM
        port_processes.assert_port_clear(port)
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)
        child.stdout.close()
        child.stderr.close()


def test_native_port_probe_accepts_reusable_time_wait_connections():
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        assert port != 7654
        server.listen(1)
        server.settimeout(2)
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            peer, _ = server.accept()
            peer.close()
            assert client.recv(1) == b""
    port_processes._check_bindable(port)
