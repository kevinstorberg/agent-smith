from __future__ import annotations

import os
import fcntl
import re
import shutil
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scripts.shared.port_processes import ListenerSnapshot, assert_port_clear, snapshot_port, terminate_port_listeners


class StartupError(RuntimeError):
    def __init__(self, stage: str, detail: str) -> None:
        self.stage = stage
        super().__init__(f"Startup {stage} failed: {detail}")


@dataclass(frozen=True)
class GitSnapshot:
    head: str
    target: str


class Checkout:
    def __init__(self, root: Path, *, run: Callable = subprocess.run,
                 which: Callable[[str], str | None] = shutil.which,
                 inherited: dict[str, str] | None = None) -> None:
        self.root = Path(root).resolve()
        self.run = run
        self.which = which
        supplied = os.environ if inherited is None else inherited
        self.env = {key: value for key, value in supplied.items() if not key.startswith("GIT_")}
        self.env["GIT_TERMINAL_PROMPT"] = "0"

    def command(self, arguments: list[str], stage: str = "PREFLIGHT", *, accepted: tuple[int, ...] = (0,)):
        try:
            result = self.run(arguments, cwd=self.root, env=self.env, capture_output=True,
                              text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise StartupError(stage, f"{Path(arguments[0]).name} could not complete; check tool availability and authentication") from None
        if result.returncode not in accepted:
            raise StartupError(stage, f"{Path(arguments[0]).name} command exited {result.returncode}; existing work was not reset")
        return result

    def git(self, *arguments: str, stage: str = "PREFLIGHT") -> str:
        return self.command(["git", *arguments], stage).stdout.strip()

    def require_tools(self, python: str) -> None:
        if not Path(python).is_file() or not os.access(python, os.X_OK):
            raise StartupError("PREFLIGHT", "the activated Python executable is unavailable; run ./setup.sh")
        for name in ("git", "node", "npm"):
            if self.which(name) is None:
                raise StartupError("PREFLIGHT", f"{name} is missing; install native dependencies before launch")
        version = self.command([python, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"]).stdout.strip()
        if version != "3.13":
            raise StartupError("PREFLIGHT", "the activated environment must use Python 3.13")
        self.command([python, "-c", "import alembic, psycopg2, uvicorn"])
        node = self.command(["node", "--version"]).stdout.strip()
        match = re.fullmatch(r"v(\d+)\.(\d+)\.\d+(?:[-+].*)?", node)
        if not match or tuple(map(int, match.groups())) < (22, 12):
            raise StartupError("PREFLIGHT", "Node.js 22.12 or newer is required")

    def require_clean_main(self, *, stage: str = "PREFLIGHT", expected: str | None = None) -> str:
        if Path(self.git("rev-parse", "--show-toplevel", stage=stage)).resolve() != self.root:
            raise StartupError(stage, "launch from the repository root")
        if self.git("branch", "--show-current", stage=stage) != "main":
            raise StartupError(stage, "the checkout must be on main; switch branches explicitly before launching")
        if self.git("status", "--porcelain=v1", "--untracked-files=all", stage=stage):
            raise StartupError(stage, "the main checkout has local changes; commit or remove them explicitly before launching")
        head = self.git("rev-parse", "--verify", "HEAD^{commit}", stage=stage)
        if expected is not None and head != expected:
            raise StartupError(stage, "the checkout changed during startup; rerun after reviewing its state")
        return head

    def preflight(self, python: str) -> GitSnapshot:
        self.require_tools(python)
        head = self.require_clean_main()
        self.git("fetch", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main")
        target = self.git("rev-parse", "--verify", "refs/remotes/origin/main^{commit}")
        if not re.fullmatch(r"[0-9a-f]{40,64}", target):
            raise StartupError("PREFLIGHT", "origin/main did not resolve to a commit")
        relation = self.command(["git", "merge-base", "--is-ancestor", head, target], accepted=(0, 1))
        if relation.returncode:
            raise StartupError("PREFLIGHT", "main is ahead of or diverged from origin/main; resolve it explicitly before launching")
        self.require_clean_main(expected=head)
        return GitSnapshot(head, target)

    def fast_forward(self, snapshot: GitSnapshot) -> None:
        self.require_clean_main(stage="UPDATING", expected=snapshot.head)
        self.git("merge", "--ff-only", snapshot.target, stage="UPDATING")
        self.require_clean_main(stage="UPDATING", expected=snapshot.target)


class StartupLease:
    def __init__(self, root: Path, descriptor: int) -> None:
        self.descriptor: int | None = None
        path = root / ".runtime/startup.lock"
        try:
            opened = os.fstat(descriptor)
            expected = path.stat()
            if (descriptor < 3 or path.is_symlink() or not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino)):
                raise ValueError
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.set_inheritable(descriptor, True)
        except (OSError, ValueError):
            raise StartupError("REEXECUTING", "the startup lock handoff is invalid; rerun ./run.sh") from None
        self.descriptor = descriptor

    def fileno(self) -> int:
        if self.descriptor is None:
            raise StartupError("REEXECUTING", "the startup lock was already released")
        return self.descriptor

    def close(self) -> None:
        descriptor, self.descriptor = self.descriptor, None
        if descriptor is not None:
            os.close(descriptor)


def startup_preparing(root: Path) -> bool:
    path = root / ".runtime/startup.lock"
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("Startup lock is not a regular file; inspect .runtime before retrying")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    finally:
        os.close(descriptor)


def stage(name: str, port: int) -> None:
    print(f"Startup {name}: API port {port}", flush=True)


def probe_database(python: str, env: dict[str, str], *, run: Callable = subprocess.run) -> None:
    code = """
import os
from contextlib import closing
import psycopg2
url = os.environ['DATABASE_URL_' + os.environ['APP_ENV'].upper()]
with closing(psycopg2.connect(url, connect_timeout=5, options='-c default_transaction_read_only=on -c statement_timeout=5000')) as connection:
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1')
        if cursor.fetchone() != (1,):
            raise RuntimeError('Database readiness response was invalid')
"""
    try:
        result = run([python, "-c", code], env=env, capture_output=True, text=True, timeout=12, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise StartupError("PREFLIGHT", "the read-only database probe timed out or could not run; check connectivity before retrying") from None
    if result.returncode != 0:
        raise StartupError("PREFLIGHT", "the read-only database probe failed; check target connectivity and credentials before retrying")


def prepare_startup(
    root: Path, python: str, port: int, inherited: dict[str, str], *,
    validate_instances: Callable[[], None], validate_database: Callable[[], None], stop_managed: Callable[[], None],
    checkout: Checkout | None = None,
    inspect_port: Callable[[int], ListenerSnapshot] = snapshot_port,
    terminate: Callable[[ListenerSnapshot], None] = terminate_port_listeners,
    clear_port: Callable[[int], None] = assert_port_clear,
) -> str:
    current_stage = "PREFLIGHT"
    try:
        stage(current_stage, port)
        validate_instances()
        checkout = checkout or Checkout(root, inherited=inherited)
        snapshot = checkout.preflight(python)
        validate_database()
        listeners = inspect_port(port)
        validate_instances()
        checkout.require_clean_main(expected=snapshot.head)
        current_stage = "STOPPING"
        stage(current_stage, port)
        stop_managed()
        terminate(listeners)
        clear_port(port)
        current_stage = "UPDATING"
        stage(current_stage, port)
        checkout.fast_forward(snapshot)
        return snapshot.target
    except StartupError:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise StartupError(current_stage, f"port={port}; {exc}") from None
