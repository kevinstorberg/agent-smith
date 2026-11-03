from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import http.client
import os
from pathlib import Path
import random
import socket
import subprocess
import sys
import time
from collections.abc import Iterator


@dataclass
class OwnedUvicorn:
    port: int
    output: Path
    process: subprocess.Popen
    shutdown_timeout: float

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=self.shutdown_timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
            raise AssertionError(f"Owned Uvicorn did not shut down within {self.shutdown_timeout:g} seconds: {self.output.read_text()}") from None


@contextmanager
def owned_uvicorn(
    code: str, output: Path, protocol: str, *, level: str = "info",
    ready_timeout: float = 5, shutdown_timeout: float = 8,
) -> Iterator[OwnedUvicorn]:
    with socket.socket() as listener, output.open("w") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        assert port != 7654
        env = {key: os.environ[key] for key in ("PATH", "TMPDIR", "TMP", "TEMP") if key in os.environ}
        env.update(AGENT_SMITH_AUTOMATED_TESTS="1", PYTHONUNBUFFERED="1", APP_ENV="test",
                   LANGCHAIN_TRACING="false", LANGCHAIN_TRACING_V2="false",
                   LANGSMITH_TRACING="false", OTEL_SDK_DISABLED="true")
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(listener.fileno()), protocol, level],
            cwd=Path(__file__).resolve().parents[1], env=env, pass_fds=(listener.fileno(),),
            stdout=log, stderr=subprocess.STDOUT,
        )
        listener.close()
        server = OwnedUvicorn(port, output, process, shutdown_timeout)
        try:
            deadline, delay, last_error = time.monotonic() + ready_timeout, 0.02, "not started"
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(f"Owned Uvicorn exited with {process.returncode}: {output.read_text()}")
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
                try:
                    connection.request("GET", "/health")
                    response = connection.getresponse()
                    response.read()
                    if response.status == 200:
                        break
                    last_error = f"health returned {response.status}"
                except (OSError, http.client.HTTPException) as error:
                    last_error = type(error).__name__
                finally:
                    connection.close()
                time.sleep(delay * random.uniform(0.8, 1.2))
                delay = min(delay * 2, 0.2)
            else:
                raise AssertionError(f"Owned Uvicorn did not become ready within {ready_timeout:g} seconds ({last_error}): {output.read_text()}")
            yield server
        finally:
            server.stop()
