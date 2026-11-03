from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import math
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable


class PortProcessError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    uid: int
    birth: str
    executable: str


@dataclass(frozen=True)
class ListenerSnapshot:
    port: int
    listeners: tuple[ProcessIdentity, ...]


class _DarwinProcessInfo(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint32), ("status", ctypes.c_uint32),
        ("xstatus", ctypes.c_uint32), ("pid", ctypes.c_uint32),
        ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32), ("svuid", ctypes.c_uint32),
        ("svgid", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32),
        ("jobc", ctypes.c_uint32), ("terminal", ctypes.c_uint32),
        ("terminal_pgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
        ("start_seconds", ctypes.c_uint64), ("start_microseconds", ctypes.c_uint64),
    ]


def _birth_token(pid: int) -> str | None:
    if sys.platform.startswith("linux"):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except FileNotFoundError:
            return None
        end_name = stat.rfind(")")
        if not stat.startswith(f"{pid} (") or end_name < 0:
            raise ValueError("Invalid Linux process birth record")
        fields = stat[end_name + 2:].split()
        if len(fields) < 20 or not fields[19].isdigit():
            raise ValueError("Invalid Linux process birth record")
        return f"linux:{fields[19]}"
    if sys.platform == "darwin":
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        query = library.proc_pidinfo
        query.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        query.restype = ctypes.c_int
        info = _DarwinProcessInfo()
        ctypes.set_errno(0)
        size = query(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size == 0 and ctypes.get_errno() == errno.ESRCH:
            return None
        if size != ctypes.sizeof(info) or info.pid != pid:
            raise OSError(ctypes.get_errno(), "Cannot inspect native process birth record")
        return f"darwin:{info.start_seconds}:{info.start_microseconds}"
    raise ValueError("Exact process birth inspection requires macOS or Linux")


def _check_bindable(port: int) -> None:
    """Detect hidden wildcard/loopback listeners; other interfaces rely on lsof visibility."""
    supported = False
    addresses = (
        (socket.AF_INET, ("0.0.0.0", port)), (socket.AF_INET, ("127.0.0.1", port)),
        (socket.AF_INET6, ("::", port)), (socket.AF_INET6, ("::1", port)),
    )
    # macOS permits a reusable wildcard bind over an existing loopback listener.
    for family, address in addresses:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if family == socket.AF_INET6:
                    probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                probe.bind(address)
                supported = True
        except OSError as error:
            if error.errno not in (errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT, errno.EADDRNOTAVAIL):
                raise
    if not supported:
        raise OSError(errno.EAFNOSUPPORT, "No supported TCP address family")


def _validate_port(port: int) -> None:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")


class PortProcesses:
    def __init__(
        self,
        *,
        run: Callable = subprocess.run,
        kill: Callable = os.kill,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        which: Callable[[str], str | None] = shutil.which,
        birth_token: Callable[[int], str | None] = _birth_token,
        check_bindable: Callable[[int], None] = _check_bindable,
        uid: int | None = None,
    ) -> None:
        self.run = run
        self.kill = kill
        self.clock = clock
        self.sleep = sleep
        self.which = which
        self.birth_token = birth_token
        self.check_bindable = check_bindable
        self.uid = os.geteuid() if uid is None else uid
        self.tools: dict[str, str] = {}

    @staticmethod
    def _error(port: int, stage: str, detail: str, pid: int | None = None) -> PortProcessError:
        target = f"port={port}" + (f", pid={pid}" if pid is not None else "")
        return PortProcessError(f"Listener cleanup failed ({target}, stage={stage}): {detail}")

    def _preflight_tools(self, port: int, stage: str) -> None:
        for name in ("lsof", "ps"):
            path = self.which(name)
            if not path:
                raise self._error(port, stage, f"required tool '{name}' is missing; install it before restarting")
            self.tools[name] = path

    def _query(self, args: list[str], port: int, stage: str, deadline: float | None = None):
        timeout = 1.0 if deadline is None else min(1.0, deadline - self.clock())
        if timeout <= 0:
            raise self._error(port, stage, "inspection timed out; inspect this port before restarting")
        try:
            return self.run(args, capture_output=True, text=True, timeout=timeout,
                            env={**os.environ, "LC_ALL": "C"})
        except (OSError, subprocess.TimeoutExpired) as error:
            raise self._error(port, stage, f"{Path(args[0]).name} inspection failed ({type(error).__name__}); no further signals sent") from None

    def _listener_pids(self, port: int, stage: str, deadline: float | None = None) -> tuple[int, ...]:
        result = self._query([self.tools["lsof"], "-nP", "-a", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"], port, stage, deadline)
        if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
            self._verify_bindable(port, stage)
            return ()
        if result.returncode != 0 or result.stderr.strip():
            raise self._error(port, stage, "lsof could not inspect listeners; check process inspection permissions")
        pids = set()
        for line in result.stdout.splitlines():
            if pids and line.startswith("f") and line[1:].isdigit():
                continue
            if not line.startswith("p") or not line[1:].isdigit() or int(line[1:]) <= 0:
                raise self._error(port, stage, "lsof returned an invalid listener identity")
            pids.add(int(line[1:]))
        if not pids:
            self._verify_bindable(port, stage)
        return tuple(sorted(pids))

    def _verify_bindable(self, port: int, stage: str) -> None:
        try:
            self.check_bindable(port)
        except OSError as error:
            detail = "port is occupied but its listener PID is not inspectable; stop it manually or fix inspection permissions"
            if error.errno != errno.EADDRINUSE:
                detail = f"cannot verify this port is available ({type(error).__name__}); check bind permissions"
            raise self._error(port, stage, detail) from None

    def _identity(self, pid: int, port: int, stage: str, deadline: float | None = None) -> ProcessIdentity | None:
        try:
            before = self.birth_token(pid)
            if before is None:
                return None
            result = self._query([self.tools["ps"], "-p", str(pid), "-o", "uid=", "-o", "comm="], port, stage, deadline)
            if result.returncode == 1 and not result.stdout.strip() and not result.stderr.strip():
                return None
            fields = result.stdout.strip().split(maxsplit=1)
            if result.returncode != 0 or result.stderr.strip() or len(fields) != 2 or not fields[0].isdigit():
                raise self._error(port, stage, "ps could not inspect process owner and executable", pid)
            after = self.birth_token(pid)
        except (OSError, ValueError) as error:
            raise self._error(port, stage, f"native identity inspection failed ({type(error).__name__})", pid) from None
        if after is None:
            return None
        if before != after:
            raise self._error(port, stage, "process identity changed during inspection; retry after inspecting this PID", pid)
        return ProcessIdentity(pid, int(fields[0]), before, fields[1])

    def _permission(self, identity: ProcessIdentity, port: int, stage: str) -> bool:
        if identity.uid != self.uid or identity.pid == os.getpid():
            raise self._error(port, stage, "listener is not an eligible process owned by this user; stop it manually", identity.pid)
        try:
            self.kill(identity.pid, 0)
        except ProcessLookupError:
            return False
        except OSError as error:
            raise self._error(port, stage, f"signal permission check failed ({type(error).__name__}); stop it manually", identity.pid) from None
        return True

    def snapshot_port(self, port: int) -> ListenerSnapshot:
        _validate_port(port)
        self._preflight_tools(port, "preflight")
        listeners = []
        for pid in self._listener_pids(port, "preflight"):
            identity = self._identity(pid, port, "preflight")
            if identity is not None and self._permission(identity, port, "preflight"):
                listeners.append(identity)
        snapshot = ListenerSnapshot(port, tuple(listeners))
        self._observe(snapshot, "preflight")
        return snapshot

    def _observe(self, snapshot: ListenerSnapshot, stage: str, deadline: float | None = None) -> tuple[ProcessIdentity, ...]:
        captured = {identity.pid: identity for identity in snapshot.listeners}
        active = []
        for pid in self._listener_pids(snapshot.port, stage, deadline):
            if pid not in captured:
                raise self._error(snapshot.port, stage, "a replacement listener appeared; no further signals sent", pid)
            current = self._identity(pid, snapshot.port, stage, deadline)
            if current is None:
                continue
            if current != captured[pid]:
                raise self._error(snapshot.port, stage, "listener identity changed; no further signals sent", pid)
            active.append(current)
        return tuple(active)

    def _signal(self, snapshot: ListenerSnapshot, identities: tuple[ProcessIdentity, ...], signum: int, stage: str, deadline: float) -> None:
        for identity in identities:
            if identity not in self._observe(snapshot, stage, deadline):
                continue
            if not self._permission(identity, snapshot.port, stage):
                continue
            if identity not in self._observe(snapshot, stage, deadline):
                continue
            try:
                self.kill(identity.pid, signum)
            except ProcessLookupError:
                pass
            except OSError as error:
                raise self._error(snapshot.port, stage, f"signal failed ({type(error).__name__}); no further signals sent", identity.pid) from None

    def _wait(self, snapshot: ListenerSnapshot, stage: str, deadline: float) -> tuple[ProcessIdentity, ...]:
        active = snapshot.listeners
        while self.clock() < deadline:
            active = self._observe(snapshot, stage, deadline)
            if not active:
                return ()
            self.sleep(min(0.1, max(0, deadline - self.clock())))
        return active

    def terminate_port_listeners(self, snapshot: ListenerSnapshot, term_timeout: float = 5, kill_timeout: float = 3) -> None:
        _validate_port(snapshot.port)
        for name, value in (("term_timeout", term_timeout), ("kill_timeout", kill_timeout)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if len({identity.pid for identity in snapshot.listeners}) != len(snapshot.listeners):
            raise ValueError("snapshot must contain distinct listener PIDs")
        self._preflight_tools(snapshot.port, "preflight")
        active = self._observe(snapshot, "preflight")
        for identity in active:
            self._permission(identity, snapshot.port, "preflight")
        if not active:
            return
        term_deadline = self.clock() + term_timeout
        self._signal(snapshot, active, signal.SIGTERM, "TERM", term_deadline)
        active = self._wait(snapshot, "TERM", term_deadline)
        if not active:
            return
        kill_deadline = self.clock() + kill_timeout
        self._signal(snapshot, active, signal.SIGKILL, "KILL", kill_deadline)
        active = self._wait(snapshot, "KILL", kill_deadline)
        if active:
            raise self._error(snapshot.port, "KILL", "listener remained after the bounded shutdown; stop it manually", active[0].pid)

    def assert_port_clear(self, port: int) -> None:
        _validate_port(port)
        self._preflight_tools(port, "verify-clear")
        pids = self._listener_pids(port, "verify-clear")
        if pids:
            raise self._error(port, "verify-clear", "port is still occupied; inspect this PID before restarting", pids[0])


def snapshot_port(port: int) -> ListenerSnapshot:
    return PortProcesses().snapshot_port(port)


def terminate_port_listeners(snapshot: ListenerSnapshot, term_timeout: float = 5, kill_timeout: float = 3) -> None:
    PortProcesses().terminate_port_listeners(snapshot, term_timeout, kill_timeout)


def assert_port_clear(port: int) -> None:
    PortProcesses().assert_port_clear(port)
