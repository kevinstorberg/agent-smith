from __future__ import annotations

import os
import fcntl
from contextlib import contextmanager
from pathlib import Path
import signal
import subprocess
import time
from typing import Iterator


class InstanceRunningError(RuntimeError):
    pass


@contextmanager
def instance_lock(root: Path, app_env: str) -> Iterator[None]:
    runtime = root / ".runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    with (runtime / f"{app_env}.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstanceRunningError(f"{app_env} is already running in this checkout; use a separate checkout or stop it first") from None
        yield


def wait_for_lock_release(root: Path, app_env: str, timeout: float) -> None:
    # The lock outlives the process record and the supervised children, so its release
    # is the earliest moment a replacement launch can take over the port and the build.
    deadline = time.monotonic() + timeout
    while True:
        try:
            with instance_lock(root, app_env):
                return
        except InstanceRunningError:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"{app_env} has not stopped after {timeout:g} seconds; inspect its log") from None
            time.sleep(0.1)


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        process.wait(timeout=5)
        return
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def supervise(commands: list[tuple[list[str], Path]], env: dict[str, str], frontend_env: dict[str, str] | None = None) -> int:
    processes = []
    stopping = False

    def request_stop(signum, frame):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for index, (command, cwd) in enumerate(commands):
            child_env = frontend_env if index and frontend_env is not None else env
            processes.append(subprocess.Popen(command, cwd=cwd, env=child_env, start_new_session=True))
        while not stopping:
            for process in processes:
                code = process.poll()
                if code is not None:
                    return (code or 1) if code >= 0 else 128 - code
            time.sleep(0.1)
        return 0
    finally:
        for process in reversed(processes):
            stop_process(process)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
