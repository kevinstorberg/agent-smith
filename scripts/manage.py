from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.shared.database_safety import production_database_url, validate_certificate, validate_database_target, validate_memory_target
from scripts.shared.env import environment
from scripts.shared.local_postgres import temporary_postgres
from scripts.shared.processes import instance_lock, supervise

CLIENT = ROOT / "services/client"
MODES = {"dev": "development", "development": "development", "prod": "production", "production": "production", "test": "test"}


def python_executable() -> str:
    configured = os.environ.get("AGENT_SMITH_PYTHON", str(ROOT / ".venv/bin/python"))
    executable = Path(shutil.which(configured) or configured)
    if not executable.is_file():
        raise RuntimeError("Python environment is missing. Run ./setup.sh once before launching.")
    return str(executable)


def selected_environment(mode: str) -> dict[str, str]:
    if mode not in MODES:
        raise ValueError("Environment must be development, test, or production")
    app_env = MODES[mode]
    env = environment(ROOT, app_env)
    url = env.get(f"DATABASE_URL_{app_env.upper()}", "")
    validate_database_target(app_env, url, production_database_url(ROOT, env))
    validate_certificate(url)
    validate_memory_target(ROOT, env)
    env["PATH"] = str(Path(python_executable()).parent) + os.pathsep + env.get("PATH", "")
    env.pop("UVICORN_RELOAD", None)
    env.pop("WEB_CONCURRENCY", None)
    return env


def checked(command: list[str], env: dict[str, str] | None = None, cwd: Path = ROOT) -> None:
    subprocess.run(command, env=env, cwd=cwd, check=True)


def frontend_environment(env: dict[str, str]) -> dict[str, str]:
    allowed = {"PATH", "HOME", "TMPDIR", "TMP", "TEMP", "CI", "NODE_OPTIONS", "NODE_ENV", "DASHBOARD_PORT", "DEV_FRONTEND_PORT"}
    # Package/build processes do not need application database or provider credentials.
    return {key: value for key, value in env.items()
            if key in allowed or key.startswith(("VITE_", "NPM_CONFIG_", "npm_config_"))}


def digest(paths: Iterable[Path]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(paths):
        hasher.update(str(path.relative_to(CLIENT)).encode())
        hasher.update(path.read_bytes())
    return hasher.hexdigest()


def frontend_inputs() -> list[Path]:
    return [*CLIENT.glob("*.json"), *CLIENT.glob("vite.config.*"), CLIENT / "index.html",
            *(p for p in (CLIENT / "src").rglob("*") if p.is_file()),
            *(p for p in (CLIENT / "public").rglob("*") if p.is_file())]


def install_frontend(force: bool = False) -> str:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("Node.js/npm is missing; install Node 22.12 or newer")
    fingerprint = digest([CLIENT / "package.json", CLIENT / "package-lock.json"])
    stamp = CLIENT / "node_modules/.agent-smith-lock-hash"
    if force or not (CLIENT / "node_modules/.bin/vite").exists() or not stamp.exists() or stamp.read_text() != fingerprint:
        checked([npm, "ci", "--no-audit", "--no-fund"], env=frontend_environment(dict(os.environ)), cwd=CLIENT)
        stamp.write_text(fingerprint)
    return npm


def build_frontend(env: dict[str, str], force: bool = False) -> None:
    fingerprint = digest(frontend_inputs())
    stamp = CLIENT / "dist/.agent-smith-source-hash"
    if not force and (CLIENT / "dist/index.html").is_file() and stamp.exists() and stamp.read_text() == fingerprint:
        print("Frontend unchanged; using existing build", flush=True)
        return
    npm = install_frontend()
    checked([npm, "run", "build"], env=frontend_environment(env), cwd=CLIENT)
    if not (CLIENT / "dist/index.html").is_file() or digest(frontend_inputs()) != fingerprint:
        raise RuntimeError("Frontend build missing or sources changed during build; retry launch")
    stamp.write_text(fingerprint)


def control_instance(mode: str, stop: bool = False) -> int:
    record = ROOT / ".runtime" / f"{MODES[mode]}.json"
    if not record.exists():
        print(f"{MODES[mode]} is not running")
        return 0
    data = json.loads(record.read_text())
    command = subprocess.run(["ps", "-p", str(data["pid"]), "-o", "command="], capture_output=True, text=True)
    if str(Path(__file__).resolve()) not in command.stdout or f"--launch-token {data['token']}" not in command.stdout:
        raise RuntimeError("Stale process record; refusing to signal an unrelated process")
    if stop:
        os.kill(data["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 35
        while record.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if record.exists():
            raise RuntimeError("Application has not stopped after 35 seconds; inspect its log")
    else:
        print(f"{MODES[mode]} running (pid={data['pid']})")
    return 0


def run_application(args: argparse.Namespace) -> int:
    if args.stop or args.status:
        return control_instance(args.mode, stop=args.stop)
    env = selected_environment(args.mode)
    port = int(env.get("DASHBOARD_PORT", "7654"))
    if not 1 <= port <= 65535:
        raise ValueError("DASHBOARD_PORT must be between 1 and 65535")
    runtime = ROOT / ".runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    if args.detach:
        log_path = runtime / f"{MODES[args.mode]}.log"
        with log_path.open("a") as log:
            log_path.chmod(0o600)
            command = [sys.executable, str(Path(__file__).resolve()), "run", args.mode,
                       "--launch-token", uuid.uuid4().hex]
            if args.rebuild:
                command.append("--rebuild")
            process = subprocess.Popen(command, env=env, stdout=log, stderr=log, start_new_session=True)
        time.sleep(0.5)
        if process.poll() is not None:
            raise RuntimeError(f"Background launch failed; inspect {log_path}")
        print(f"Launch started (pid={process.pid}); log: {log_path}. Use ./run.sh {args.mode} --status or --stop.")
        return 0
    if not args.launch_token:
        os.execve(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:],
                                  "--launch-token", uuid.uuid4().hex], env)
    with instance_lock(ROOT, MODES[args.mode]):
        python = python_executable()
        commands = [([python, "-m", "uvicorn", "services.api.app:app", "--workers", "1", "--host", env.get("DASHBOARD_HOST", "127.0.0.1"), "--port", str(port)], ROOT)]
        if MODES[args.mode] == "development":
            npm = install_frontend()
            commands[0][0].extend(["--reload", "--reload-dir", "services", "--reload-dir", "scripts"])
            commands.append(([npm, "run", "dev", "--", "--strictPort"], CLIENT))
        else:
            build_frontend(env, force=args.rebuild)
        record = runtime / f"{MODES[args.mode]}.json"
        record.write_text(json.dumps({"pid": os.getpid(), "token": args.launch_token}))
        record.chmod(0o600)
        try:
            return supervise(commands, env, frontend_env=frontend_environment(env))
        finally:
            record.unlink(missing_ok=True)


def audit(args: argparse.Namespace, extra: list[str]) -> None:
    python = python_executable()
    checked([python, "-m", "ruff", "check", "."])
    with temporary_postgres() as url:
        env = environment(ROOT, "test")
        env["DATABASE_URL_TEST"] = url
        # Both SQL and local vector memory are discarded with the owned temporary cluster.
        import tempfile
        with tempfile.TemporaryDirectory(prefix="agent-smith-test-memory-") as store:
            env["MEMORY_STORE_PATH"] = store
            env["MEMORY_BACKEND"] = "lancedb"
            checked([python, "-m", "pytest", "tests/", "-v", *extra], env=env)
    if not args.backend_only:
        with instance_lock(ROOT, "production"):
            npm = install_frontend()
            for task in ("lint", "test", "build"):
                checked([npm, "run", task], env=frontend_environment(dict(os.environ)), cwd=CLIENT)


def upgrade_database(args: argparse.Namespace) -> None:
    env = selected_environment(args.mode)
    env["AGENT_SMITH_CONFIRM_DATABASE"] = args.confirm_database or ""
    checked([python_executable(), str(ROOT / "scripts/upgrade_database.py")], env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Native Agent Smith lifecycle commands")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("mode", nargs="?", choices=["dev", "development", "prod", "production"], default="production")
    run.add_argument("-d", "--detach", action="store_true")
    run.add_argument("-nc", "--rebuild", action="store_true")
    run.add_argument("--stop", action="store_true")
    run.add_argument("--status", action="store_true")
    run.add_argument("--launch-token", help=argparse.SUPPRESS)
    audit_parser = commands.add_parser("audit")
    audit_parser.add_argument("--backend-only", action="store_true")
    for command in ("evals", "sync", "erd", "upgrade"):
        sub = commands.add_parser(command)
        sub.add_argument("--env" if command != "upgrade" else "mode", choices=list(MODES), default=os.environ.get("APP_ENV", "production" if command == "evals" else "development"))
        if command == "upgrade":
            sub.add_argument("--confirm-database")
    args, extra = parser.parse_known_args()
    if extra and args.command not in {"audit", "evals", "sync"}:
        parser.error(f"Unrecognized arguments: {' '.join(extra)}")
    try:
        if args.command == "run":
            return run_application(args)
        if args.command == "audit":
            audit(args, extra)
        elif args.command == "upgrade":
            upgrade_database(args)
        else:
            env = selected_environment(args.env)
            if args.command == "evals":
                env["AGENT_SMITH_EVAL_RUN"] = "1"
                checked([python_executable(), "-m", "pytest", "evals/test_suite.py", "-v", *extra], env=env)
            elif args.command == "sync":
                checked([python_executable(), str(ROOT / "scripts/sync.py"), *extra], env=env)
            elif args.command == "erd":
                if not shutil.which("dot"):
                    raise RuntimeError("Graphviz is missing; install it to generate the ERD")
                checked([python_executable(), str(ROOT / "scripts/generate_erd.py"), "-o", str(ROOT / "docs/erd.png")], env=env)
        return 0
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        message = f"Command failed with exit code {exc.returncode}" if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"Agent Smith: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
