from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import venv
from contextlib import ExitStack

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.manage import install_frontend
from scripts.shared.processes import instance_lock


def main() -> None:
    parser = argparse.ArgumentParser(description="Install native Agent Smith dependencies once")
    parser.add_argument("--refresh", action="store_true", help="Refresh Python and npm dependencies")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 13):
        raise SystemExit("Setup requires Python 3.13. Install it or set PYTHON_BIN to its executable.")
    with ExitStack() as stack:
        for app_env in ("production", "development"):
            stack.enter_context(instance_lock(ROOT, app_env))
        python = ROOT / ".venv/bin/python"
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(ROOT / ".venv")
        version = subprocess.check_output([str(python), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"], text=True).strip()
        if version != "3.13":
            raise SystemExit("Existing .venv uses a different Python version; recreate it with Python 3.13 before setup")
        requirements = ROOT / "requirements.txt"
        fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
        stamp = ROOT / ".venv/.agent-smith-requirements-hash"
        if args.refresh or not stamp.exists() or stamp.read_text() != fingerprint:
            command = [str(python), "-m", "pip", "install", "-r", str(requirements)]
            if args.refresh:
                command.append("--upgrade")
            subprocess.run(command, check=True)
            stamp.write_text(fingerprint)
        install_frontend(force=args.refresh)
    print("Native dependencies ready. Configure .env.development/.env.production, then run ./run.sh dev or ./run.sh.")


if __name__ == "__main__":
    main()
