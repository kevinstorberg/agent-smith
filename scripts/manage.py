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

from scripts.shared.database_safety import database_identity, production_database_url, validate_certificate, validate_database_target, validate_memory_target
from scripts.shared.env import environment
from scripts.shared.local_postgres import temporary_postgres
from scripts.shared.processes import InstanceRunningError, instance_lock, supervise, wait_for_lock_release
from scripts.shared.native_startup import Checkout, StartupError, StartupLease, prepare_startup, probe_database, stage, startup_preparing
from scripts.shared.port_processes import assert_port_clear
from scripts.shared.automated_tests import AUTOMATED_TESTS_ENV, require_model_calls_allowed

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
        return
    npm = install_frontend()
    checked([npm, "run", "build"], env=frontend_environment(env), cwd=CLIENT)
    if not (CLIENT / "dist/index.html").is_file() or digest(frontend_inputs()) != fingerprint:
        raise RuntimeError("Frontend build missing or sources changed during build; retry launch")
    stamp.write_text(fingerprint)


def running_instance(mode: str) -> int | None:
    record = ROOT / ".runtime" / f"{MODES[mode]}.json"
    if not record.exists():
        return None
    data = json.loads(record.read_text())
    command = subprocess.run(["ps", "-ww", "-p", str(data["pid"]), "-o", "command="], capture_output=True, text=True)
    if not command.stdout.strip():
        # A launcher killed without cleanup (e.g. SIGKILL) leaves its record behind; no process to signal.
        record.unlink(missing_ok=True)
        return None
    if str(Path(__file__).resolve()) not in command.stdout or f"--launch-token {data['token']}" not in command.stdout:
        raise RuntimeError("Stale process record; refusing to signal an unrelated process")
    return data["pid"]


def stop_instance(mode: str, pid: int) -> None:
    os.kill(pid, signal.SIGTERM)
    # A launcher suspended in its terminal (Ctrl+Z) keeps SIGTERM pending until it is resumed.
    os.kill(pid, signal.SIGCONT)
    wait_for_lock_release(ROOT, MODES[mode], timeout=35)


def control_instance(mode: str, stop: bool = False) -> int:
    preparing = startup_preparing(ROOT)
    log_hint = f"inspect {ROOT / '.runtime'} for production.log or development.log"
    if preparing and stop:
        raise RuntimeError(f"Startup preparing in this checkout; no stop signal was sent; {log_hint}")
    pid = running_instance(mode)
    if pid is None:
        print(f"Startup preparing in this checkout; {log_hint}" if preparing else f"{MODES[mode]} is not running")
    elif stop:
        stop_instance(mode, pid)
    else:
        print(f"{MODES[mode]} running (pid={pid})")
    return 0


def replace_running_instance(mode: str) -> None:
    pid = running_instance(mode)
    if pid is not None:
        print(f"Stopping running {MODES[mode]} (pid={pid}) before relaunch")
        stop_instance(mode, pid)


def validate_startup_instances(mode: str) -> None:
    active_mode = MODES[mode]
    for candidate in ("production", "development"):
        pid = running_instance(candidate)
        try:
            with instance_lock(ROOT, candidate):
                locked = False
        except InstanceRunningError:
            locked = True
        if candidate != active_mode and (pid is not None or locked):
            raise StartupError("PREFLIGHT", f"{candidate} is active in this checkout; stop it explicitly or use another checkout")
        if candidate == active_mode and locked and pid is None:
            raise StartupError("PREFLIGHT", f"{candidate} startup is already preparing; wait for its process record")


def launch_command(args: argparse.Namespace, python: str, token: str, revision: str, descriptor: int, *, detach: bool = False) -> list[str]:
    command = [python, str(Path(__file__).resolve()), "run", args.mode,
               "--launch-token", token, "--startup-revision", revision, "--startup-lock-fd", str(descriptor)]
    if args.rebuild:
        command.append("--rebuild")
    if detach:
        command.append("--detach")
    return command


def run_application(args: argparse.Namespace) -> int:
    if args.stop or args.status:
        return control_instance(args.mode, stop=args.stop)
    inherited = dict(os.environ)
    try:
        env = selected_environment(args.mode)
        port = int(env.get("DASHBOARD_PORT", "7654"))
        if not 1 <= port <= 65535:
            raise ValueError("DASHBOARD_PORT must be between 1 and 65535")
    except (OSError, ValueError, RuntimeError) as exc:
        raise StartupError("PREFLIGHT" if not args.launch_token else "REEXECUTING", str(exc)) from None
    python = python_executable()
    if not args.launch_token:
        lock = ROOT / ".runtime/startup.lock"
        if lock.is_symlink():
            raise StartupError("PREFLIGHT", "the startup lock must not be a symbolic link")
        with instance_lock(ROOT, "startup", inherit=True) as descriptor:
            revision = prepare_startup(ROOT, python, port, inherited,
                                       validate_instances=lambda: validate_startup_instances(args.mode),
                                       validate_database=lambda: probe_database(python, env),
                                       stop_managed=lambda: replace_running_instance(args.mode))
            stage("REEXECUTING", port)
            os.execve(python, launch_command(args, python, uuid.uuid4().hex, revision, descriptor, detach=args.detach), inherited)
        raise StartupError("REEXECUTING", "the updated launcher did not replace the original process")

    descriptor = getattr(args, "startup_lock_fd", None)
    revision = getattr(args, "startup_revision", None)
    if descriptor is None or revision is None:
        raise StartupError("REEXECUTING", "an internal launch requires its prepared revision and startup lock")
    lease = StartupLease(ROOT, descriptor)
    try:
        Checkout(ROOT, inherited=inherited).require_clean_main(stage="REEXECUTING", expected=revision)
        validate_startup_instances(args.mode)
        return launch_prepared_application(args, env, inherited, python, port, revision, lease)
    finally:
        lease.close()


def launch_prepared_application(args: argparse.Namespace, env: dict[str, str], inherited: dict[str, str],
                                python: str, port: int, revision: str, lease: StartupLease) -> int:
    runtime = ROOT / ".runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    if args.detach:
        log_path = runtime / f"{MODES[args.mode]}.log"
        with log_path.open("a") as log:
            log_path.chmod(0o600)
            command = launch_command(args, python, args.launch_token, revision, lease.fileno())
            process = subprocess.Popen(command, env=inherited, stdout=log, stderr=log,
                                       start_new_session=True, pass_fds=(lease.fileno(),))
        time.sleep(0.5)
        if process.poll() is not None:
            raise RuntimeError(f"Background launch failed; inspect {log_path}")
        print(f"Launch started (pid={process.pid}); log: {log_path}. Use ./run.sh {args.mode} --status or --stop.")
        return 0
    with instance_lock(ROOT, MODES[args.mode]):
        assert_port_clear(port)
        if MODES[args.mode] == "production":
            stage("MIGRATING", port)
            try:
                name = database_identity(env["DATABASE_URL_PRODUCTION"])[2]
                apply_database_upgrade(env, name)
            except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
                raise StartupError("MIGRATING", "the database upgrade failed; inspect the database state and rerun; no downgrade was attempted") from None
        stage("BUILDING", port)
        commands = [([python, "-m", "uvicorn", "services.api.app:app", "--workers", "1", "--host", env.get("DASHBOARD_HOST", "127.0.0.1"), "--port", str(port)], ROOT)]
        try:
            if MODES[args.mode] == "development":
                npm = install_frontend()
                commands[0][0].extend(["--reload", "--reload-dir", "services", "--reload-dir", "scripts"])
                commands.append(([npm, "run", "dev", "--", "--strictPort"], CLIENT))
            else:
                build_frontend(env, force=args.rebuild)
        except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError):
            raise StartupError("BUILDING", "frontend preparation failed; correct dependencies or build errors, then rerun ./run.sh") from None
        record = runtime / f"{MODES[args.mode]}.json"
        record.write_text(json.dumps({"pid": os.getpid(), "token": args.launch_token}))
        record.chmod(0o600)
        try:
            lease.close()
            stage("STARTING", port)
            return supervise(commands, env, frontend_env=frontend_environment(env))
        finally:
            record.unlink(missing_ok=True)


def audit(args: argparse.Namespace, extra: list[str]) -> None:
    python = python_executable()
    checked([python, "-m", "ruff", "check", "."])
    with temporary_postgres() as url:
        env = environment(ROOT, "test", inherited={**os.environ, AUTOMATED_TESTS_ENV: "1"})
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


def apply_database_upgrade(env: dict[str, str], confirm_database: str | None) -> None:
    approved = {**env, "AGENT_SMITH_CONFIRM_DATABASE": confirm_database or ""}
    checked([python_executable(), str(ROOT / "scripts/upgrade_database.py")], env=approved)


def upgrade_database(args: argparse.Namespace) -> None:
    apply_database_upgrade(selected_environment(args.mode), args.confirm_database)


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
    run.add_argument("--startup-revision", help=argparse.SUPPRESS)
    run.add_argument("--startup-lock-fd", type=int, help=argparse.SUPPRESS)
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
            if args.command == "evals":
                require_model_calls_allowed()
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
