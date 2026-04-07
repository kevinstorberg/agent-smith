#!/usr/bin/env python3
"""Install graphviz inside a Debian container, with snapshot mirror fallback.

apt-get install can fail when deb.debian.org serves corrupted packages during
mirror syncs. This script catches those failures and fetches broken packages
from snapshot.debian.org instead.
"""
from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
from pathlib import Path

SNAPSHOT_BASE = "http://snapshot.debian.org/archive/debian/20250330T000000Z"


def run(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def extract_failed_packages(stderr: str) -> list[tuple[str, str]]:
    failed = []
    for match in re.finditer(r"Failed to fetch http://deb\.debian\.org/debian/pool/(\S+\.deb)", stderr):
        deb_path = match.group(1)
        name = deb_path.rsplit("/", 1)[-1]
        snapshot_url = f"{SNAPSHOT_BASE}/pool/{deb_path}"
        failed.append((name, snapshot_url))
    return failed


def main() -> int:
    print("Updating package lists...")
    run("apt-get update")

    print("Installing graphviz...")
    result = run("apt-get install -y graphviz")

    if result.returncode == 0:
        run("dot -c")
        print("graphviz installed successfully")
        return 0

    failed = extract_failed_packages(result.stderr)
    if not failed:
        print(f"apt-get failed with unknown error:\n{result.stderr}", file=sys.stderr)
        return 1

    print(f"Fetching {len(failed)} broken package(s) from snapshot mirror...")
    for name, url in failed:
        print(f"  {name}")
        try:
            urllib.request.urlretrieve(url, name)
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            return 1

    deb_files = " ".join(name for name, _ in failed)
    result = run(f"dpkg -i {deb_files}")
    if result.returncode != 0:
        print(f"dpkg failed:\n{result.stderr}", file=sys.stderr)

    result = run("apt-get install -y -f graphviz")
    if result.returncode != 0:
        print(f"apt-get fix failed:\n{result.stderr}", file=sys.stderr)
        return 1

    run("dot -c")

    for name, _ in failed:
        Path(name).unlink(missing_ok=True)

    print("graphviz installed successfully (via snapshot fallback)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
