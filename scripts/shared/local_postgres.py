from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def postgres_binary(name: str) -> str:
    configured = os.environ.get("POSTGRES_BIN")
    if configured:
        candidate = Path(configured) / name
    else:
        found = shutil.which(name)
        if found:
            return found
        pg_config = shutil.which("pg_config")
        if not pg_config:
            raise RuntimeError("Native PostgreSQL binaries are missing. Install PostgreSQL 17 and set POSTGRES_BIN to its bin directory.")
        candidate = Path(subprocess.check_output([pg_config, "--bindir"], text=True).strip()) / name
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeError(f"PostgreSQL executable {name} is missing; set POSTGRES_BIN to the server bin directory")
    return str(candidate)


def run_postgres(command: list[str], timeout: int, log: Path) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        details = log.read_text()[-4000:] if log.exists() else getattr(exc, "stderr", "")
        raise RuntimeError(f"Temporary PostgreSQL {Path(command[0]).name} failed: {details}") from exc


@contextmanager
def temporary_postgres() -> Iterator[str]:
    initdb, pg_ctl = postgres_binary("initdb"), postgres_binary("pg_ctl")
    postgres_binary("postgres")
    if os.geteuid() == 0:
        raise RuntimeError("Run native tests as a normal user; PostgreSQL refuses to initialize as root")
    with tempfile.TemporaryDirectory(prefix="agent-smith-test-", dir="/tmp") as directory:
        root = Path(directory)
        data, log = root / "data", root / "postgres.log"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        try:
            run_postgres([initdb, "-D", str(data), "-U", "agent_smith_test", "--auth=trust", "--no-locale", "--encoding=UTF8"], 60, log)
            # This fresh cluster has no production credentials or data. Its socket is private.
            run_postgres([pg_ctl, "-D", str(data), "-l", str(log), "-w", "-t", "30", "-o",
                          f"-h 127.0.0.1 -p {port} -k {root}", "start"], 40, log)
            yield f"postgresql://agent_smith_test@127.0.0.1:{port}/agent_smith_test"
        finally:
            if (data / "postmaster.pid").exists():
                run_postgres([pg_ctl, "-D", str(data), "-w", "-t", "30", "stop", "-m", "immediate"], 40, log)
