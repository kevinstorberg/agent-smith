from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.shared.atomic_json import exclusive_file_lock

logger = logging.getLogger(__name__)
_OID = re.compile(r"[0-9a-f]{40}\Z")


class CommandError(RuntimeError):
    def __init__(self, program: str, code: int, output: str = "") -> None:
        super().__init__(f"{program} command failed with exit {code}")
        self.code = code
        self.output = output


def _run(argv: list[str], *, cwd: Path) -> str:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GH_HOST="github.com"
    )
    logger.debug("Repository command started program=%s", argv[0])
    try:
        result = subprocess.run(
            argv,
            cwd=cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        logger.error(
            "Repository command failed program=%s reason=%s",
            argv[0],
            type(error).__name__,
        )
        raise RuntimeError(
            f"{argv[0]} is unavailable or timed out after 30 seconds"
        ) from None
    if result.returncode:
        logger.debug(
            "Repository command failed program=%s exit=%s", argv[0], result.returncode
        )
        raise CommandError(argv[0], result.returncode, result.stdout)
    if argv[0] == "lsof" and result.stderr:
        raise RuntimeError("Process inventory is incomplete; inspect lsof permissions")
    logger.debug("Repository command succeeded program=%s", argv[0])
    return result.stdout


def _active_paths() -> set[Path]:
    output = _run(["lsof", "-nP", "-F0pn"], cwd=Path.cwd())
    paths = set()
    for record in output.split("\0"):
        record = record.lstrip("\n")
        if record.startswith("n/"):
            paths.add(Path(record[1:]))
    return paths


def _worktrees(repository: Path) -> list[dict]:
    records, current = [], {}
    for token in _run(
        ["git", "worktree", "list", "--porcelain", "-z"], cwd=repository
    ).split("\0"):
        if not token:
            if current:
                records.append(current)
                current = {}
        else:
            key, _, value = token.partition(" ")
            current[key] = value
    if current:
        records.append(current)
    if not records:
        raise ValueError("Git worktree inventory is empty")
    for record in records:
        if not Path(record.get("worktree", "")).is_absolute() or not _OID.fullmatch(
            record.get("HEAD", "")
        ):
            raise ValueError("Invalid Git worktree inventory")
    return records


def _branches(repository: Path) -> dict[str, str]:
    output = _run(
        ["git", "for-each-ref", "--format=%(refname)%00%(objectname)%00", "refs/heads"],
        cwd=repository,
    ).split("\0")
    branches = {}
    for index in range(0, len(output) - 1, 2):
        ref, head = output[index].removeprefix("\n"), output[index + 1]
        if not ref.startswith("refs/heads/") or not _OID.fullmatch(head):
            raise ValueError("Invalid Git branch inventory")
        branches[ref.removeprefix("refs/heads/")] = head
    return branches


def _github_name(url: str) -> str:
    match = re.fullmatch(
        r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/?",
        url,
    )
    if not match:
        raise ValueError(
            "Origin must identify a GitHub repository without embedded credentials"
        )
    return match[1].removesuffix(".git")


def _pages(value: str) -> list:
    try:
        pages = json.loads(value)
    except ValueError:
        raise ValueError("GitHub returned invalid JSON") from None
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ValueError("GitHub returned invalid paginated evidence")
    return [entry for page in pages for entry in page]


@dataclass(frozen=True)
class Proof:
    number: int
    head: str
    merge: str | None
    branch: str
    base: str


class GitHub:
    def __init__(self, repository: Path) -> None:
        self.repository = repository
        self.name = _github_name(
            _run(["git", "remote", "get-url", "origin"], cwd=repository).removesuffix(
                "\n"
            )
        )
        push = _github_name(
            _run(
                ["git", "remote", "get-url", "--push", "origin"], cwd=repository
            ).removesuffix("\n")
        )
        if push != self.name:
            raise ValueError("GitHub origin and push repository must agree")
        try:
            metadata = json.loads(
                _run(
                    [
                        "gh",
                        "repo",
                        "view",
                        self.name,
                        "--json",
                        "nameWithOwner,defaultBranchRef",
                    ],
                    cwd=repository,
                )
            )
            if (
                metadata["nameWithOwner"] != self.name
                or not isinstance(metadata["defaultBranchRef"]["name"], str)
                or not metadata["defaultBranchRef"]["name"]
            ):
                raise ValueError
            self.default = metadata["defaultBranchRef"]["name"]
        except (ValueError, KeyError, TypeError):
            raise ValueError(
                "GitHub repository identity or default branch is invalid"
            ) from None

    def api(self, endpoint: str) -> list:
        return _pages(
            _run(
                ["gh", "api", "--paginate", "--slurp", f"repos/{self.name}/{endpoint}"],
                cwd=self.repository,
            )
        )

    def pulls(self, commit: str | None = None) -> list[dict]:
        endpoint = (
            f"commits/{commit}/pulls?per_page=100"
            if commit
            else "pulls?state=all&per_page=100"
        )
        try:
            records = self.api(endpoint)
        except CommandError as error:
            # An unpublished commit has no GitHub association; other API failures remain fatal.
            if commit:
                try:
                    response = json.loads(error.output)
                except ValueError:
                    response = {}
                if isinstance(response, list) and len(response) == 1:
                    response = response[0]
                if (
                    isinstance(response, dict)
                    and response.get("status") in ("422", 422)
                    and response.get("message", "").startswith("No commit found")
                ):
                    return []
            raise
        for record in records:
            try:
                head, base = record["head"], record["base"]
                if (
                    type(record["number"]) is not int
                    or record["number"] <= 0
                    or record["state"] not in {"open", "closed"}
                ):
                    raise ValueError
                if (
                    not _OID.fullmatch(head["sha"])
                    or not isinstance(head["ref"], str)
                    or not isinstance(base["ref"], str)
                ):
                    raise ValueError
                if base["repo"]["full_name"] != self.name:
                    raise ValueError
                merged, merge = record.get("merged_at"), record.get("merge_commit_sha")
                if merged is not None and (
                    not isinstance(merged, str)
                    or not merged
                    or record["state"] != "closed"
                    or not isinstance(merge, str)
                    or not _OID.fullmatch(merge)
                ):
                    raise ValueError
                if head.get("repo") is not None and not isinstance(
                    head["repo"].get("full_name"), str
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError, AttributeError):
                raise ValueError(
                    "GitHub returned malformed or foreign-repository PR evidence"
                ) from None
        return records

    def remote_branches(self) -> list[dict]:
        records = self.api("branches?per_page=100")
        for record in records:
            try:
                if (
                    not isinstance(record["name"], str)
                    or not _OID.fullmatch(record["commit"]["sha"])
                    or type(record["protected"]) is not bool
                ):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise ValueError("GitHub returned malformed branch evidence") from None
        return records


def _contains(repository: Path, tip: str, head: str) -> bool:
    if tip == head:
        return True
    try:
        _run(["git", "merge-base", "--is-ancestor", tip, head], cwd=repository)
        return True
    except CommandError as error:
        if error.code in (1, 128):
            return False
        raise


def _proof(
    repository: Path, github: GitHub, pulls: list[dict], branch: str | None, tip: str
) -> tuple[Proof | None, str]:
    named = [record for record in pulls if branch and record["head"]["ref"] == branch]
    if any(record["state"] == "open" for record in named):
        return None, "An open PR uses this branch"
    if any(
        not record.get("merged_at") and record["head"]["sha"] == tip for record in named
    ):
        return None, "The current tip belongs to a closed unmerged PR"
    for records in (named, None):
        if records is None:
            records = github.pulls(tip)
        for record in records:
            head = record["head"]
            if (
                not record.get("merged_at")
                or (head.get("repo") or {}).get("full_name") != github.name
            ):
                continue
            is_result = tip == record.get("merge_commit_sha") and (
                branch is None or branch in {head["ref"], record["base"]["ref"]}
            )
            if is_result or _contains(repository, tip, head["sha"]):
                return Proof(
                    record["number"],
                    head["sha"],
                    record.get("merge_commit_sha"),
                    head["ref"],
                    record["base"]["ref"],
                ), "Confirmed MERGED PR with exact tip containment"
    return (
        None,
        "No merged PR contains this tip; closed, unpublished or newer work is retained",
    )


def _linked(path: Path) -> bool:
    return any(parent.is_symlink() for parent in (path, *path.parents))


def _symlinks(roots: list[Path], worktree_paths: set[Path]) -> list[tuple[Path, Path]]:
    result = []
    deadline = time.monotonic() + 30
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue

        def failed(error: OSError) -> None:
            raise RuntimeError(
                "Cannot inspect repository dependency references"
            ) from error

        for directory, directories, files in os.walk(
            root, followlinks=False, onerror=failed
        ):
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "Repository dependency inspection timed out after 30 seconds"
                )
            folder = Path(directory)
            for name in [*directories, *files]:
                path = folder / name
                if path.is_symlink():
                    target = path.resolve()
                    if any(
                        target.is_relative_to(candidate) for candidate in worktree_paths
                    ):
                        result.append((path, target))
            directories[:] = [
                name
                for name in directories
                if name != ".git"
                and not (folder / name).is_symlink()
                and (folder / name) not in worktree_paths
            ]
    return result


def _remote_head(repository: Path, name: str) -> str | None:
    output = _run(
        ["git", "ls-remote", "--heads", "origin", f"refs/heads/{name}"], cwd=repository
    )
    if not output:
        return None
    fields = output.rstrip("\n").split("\t")
    if (
        len(fields) != 2
        or fields[1] != f"refs/heads/{name}"
        or not _OID.fullmatch(fields[0])
    ):
        raise ValueError("Remote ref response is invalid")
    return fields[0]


def _delete_remote(repository: Path, name: str, expected: str) -> None:
    if _remote_head(repository, name) != expected:
        raise RuntimeError("Remote ref changed since inventory")
    _run(
        [
            "git",
            "push",
            "origin",
            f":refs/heads/{name}",
            f"--force-with-lease=refs/heads/{name}:{expected}",
        ],
        cwd=repository,
    )
    if _remote_head(repository, name) is not None:
        raise RuntimeError("Remote deletion did not remove the expected ref")


class Cleanup:
    def __init__(
        self, path: str, *, execute: bool, force: bool, delete_remote: bool
    ) -> None:
        candidate = Path(path) if isinstance(path, str) and path else None
        if (
            candidate is None
            or not candidate.is_absolute()
            or not candidate.is_dir()
            or candidate.is_symlink()
        ):
            raise ValueError("Repository path must be an existing absolute directory")
        if any(type(value) is not bool for value in (execute, force, delete_remote)):
            raise ValueError("Cleanup controls must be booleans")
        if (
            _run(["git", "rev-parse", "--is-bare-repository"], cwd=candidate).strip()
            != "false"
        ):
            raise ValueError("Cleanup requires a non-bare repository")
        self.worktrees = _worktrees(candidate)
        self.root = Path(self.worktrees[0]["worktree"])
        self.common = Path(
            _run(
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                cwd=candidate,
            ).removesuffix("\n")
        )
        self.github = GitHub(self.root)
        self.execute, self.force, self.delete_remote = execute, force, delete_remote
        self.protected = {"main", "master", "staging", self.github.default}
        self.protected_paths = {
            candidate.resolve(),
            self.root,
            Path.cwd().resolve(),
            Path(__file__).resolve(),
            Path(sys.executable).resolve(),
        }
        for worktree in self.worktrees:
            if any(
                path.is_relative_to(Path(worktree["worktree"]))
                for path in self.protected_paths
            ):
                self.protected.add(
                    worktree.get("branch", "").removeprefix("refs/heads/")
                )
        self.pulls = self.github.pulls()
        self.active = _active_paths()
        self.dependencies = _symlinks(
            [Path(w["worktree"]) for w in self.worktrees],
            {Path(w["worktree"]) for w in self.worktrees[1:]},
        )
        self.report = {
            "repository": str(self.root),
            "github_repository": self.github.name,
            "execute": execute,
            "force": force,
            "delete_remote": delete_remote,
            "items": [],
            "summary": {},
            "errors": [],
        }
        self.proofs: dict[tuple[str, str], Proof] = {}

    def safety(self, worktree: dict) -> str | None:
        path = Path(worktree["worktree"])
        branch = worktree.get("branch", "").removeprefix("refs/heads/")
        if (
            path == self.root
            or branch in self.protected
            or any(value.is_relative_to(path) for value in self.protected_paths)
        ):
            return "Protected primary/current checkout or branch"
        if "locked" in worktree:
            return "Worktree is locked"
        if _linked(path):
            return "Worktree path is a symbolic link"
        if any(value.is_relative_to(path) for value in self.active):
            return "An active process uses this worktree"
        if any(
            source.exists()
            and target.is_relative_to(path)
            and not source.is_relative_to(path)
            for source, target in self.dependencies
        ):
            return "Another checkout references this dependency target"
        if not self.force and _run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignored=matching",
            ],
            cwd=path,
        ):
            return "Worktree is dirty; force is required"
        return None

    def item(
        self,
        kind: str,
        name: str,
        head: str,
        branch: str | None,
        reason: str | None = None,
    ) -> dict:
        proof, evidence_reason = (
            (None, reason)
            if reason
            else _proof(self.root, self.github, self.pulls, branch, head)
        )
        item = {
            "kind": kind,
            "name": name,
            "head": head,
            "state": "eligible" if proof else "skipped",
            "reason": reason or evidence_reason,
            "pr": proof.number if proof else None,
        }
        self.report["items"].append(item)
        if proof:
            item["proof"] = asdict(proof)
        logger.info(
            "Repository cleanup inventory kind=%s name=%r state=%s pr=%s",
            kind,
            name,
            item["state"],
            item["pr"],
        )
        if proof:
            self.proofs[kind, name] = proof
        return item

    def inventory(self) -> None:
        retained = set()
        for worktree in self.worktrees:
            branch = worktree.get("branch", "").removeprefix("refs/heads/") or None
            item = self.item(
                "worktree",
                worktree["worktree"],
                worktree["HEAD"],
                branch,
                self.safety(worktree),
            )
            if item["state"] != "eligible" and branch:
                retained.add(branch)
        for branch, head in _branches(self.root).items():
            reason = (
                "Protected branch"
                if branch in self.protected
                else (
                    "Branch is checked out in a retained worktree"
                    if branch in retained
                    else None
                )
            )
            self.item("local_branch", branch, head, branch, reason)
        if self.delete_remote:
            for branch in self.github.remote_branches():
                name = branch["name"]
                reason = (
                    "Protected remote branch"
                    if branch["protected"] or name in self.protected
                    else None
                )
                self.item("remote_branch", name, branch["commit"]["sha"], name, reason)

    def revalidate(self, item: dict) -> str | None:
        proof = self.proofs[item["kind"], item["name"]]
        live = GitHub(self.root)
        if live.name != self.github.name:
            return "GitHub repository changed since inventory"
        self.protected.add(live.default)
        pulls = live.pulls()
        current = next((p for p in pulls if p["number"] == proof.number), None)
        branch = (
            next(
                (
                    w.get("branch", "").removeprefix("refs/heads/")
                    for w in self.worktrees
                    if w["worktree"] == item["name"]
                ),
                None,
            )
            if item["kind"] == "worktree"
            else item["name"]
        )
        if branch in self.protected:
            return "Protected branch"
        if (
            not current
            or not current.get("merged_at")
            or current["head"]["sha"] != proof.head
            or current.get("merge_commit_sha") != proof.merge
            or (current["head"].get("repo") or {}).get("full_name") != live.name
        ):
            return "GitHub merged proof changed since inventory"
        if any(p["state"] == "open" and p["head"]["ref"] == branch for p in pulls):
            return "An open PR now uses this branch"
        self.active = _active_paths()
        worktrees = _worktrees(self.root)
        if item["kind"] == "worktree":
            self.dependencies = _symlinks(
                [Path(w["worktree"]) for w in worktrees],
                {Path(w["worktree"]) for w in worktrees[1:]},
            )
            actual = next((w for w in worktrees if w["worktree"] == item["name"]), None)
            frozen = next(w for w in self.worktrees if w["worktree"] == item["name"])
            if (
                actual is None
                or actual.get("HEAD") != item["head"]
                or actual.get("branch") != frozen.get("branch")
            ):
                return "Worktree HEAD or branch changed since inventory"
            return self.safety(actual)
        if item["kind"] == "local_branch":
            if _branches(self.root).get(item["name"]) != item["head"]:
                return "Local branch changed since inventory"
            if any(w.get("branch") == f"refs/heads/{item['name']}" for w in worktrees):
                return "Branch is still checked out in a worktree"
        if item["kind"] == "remote_branch":
            metadata = next(
                (b for b in live.remote_branches() if b["name"] == item["name"]), None
            )
            if (
                not metadata
                or metadata["protected"]
                or metadata["commit"]["sha"] != item["head"]
                or _remote_head(self.root, item["name"]) != item["head"]
            ):
                return "Remote branch protection or tip changed since inventory"
        return None

    def mutate(self, item: dict) -> None:
        logger.info(
            "Repository cleanup attempt kind=%s name=%r head=%s pr=%s",
            item["kind"],
            item["name"],
            item["head"],
            item["pr"],
        )
        try:
            reason = self.revalidate(item)
            if reason:
                item.update(state="skipped", reason=reason)
            elif item["kind"] == "worktree":
                argv = ["git", "worktree", "remove"]
                if self.force:
                    argv.append("--force")
                _run([*argv, "--", item["name"]], cwd=self.root)
                if os.path.lexists(item["name"]) or any(
                    w["worktree"] == item["name"] for w in _worktrees(self.root)
                ):
                    raise RuntimeError("Worktree removal postcondition failed")
            elif item["kind"] == "local_branch":
                _run(
                    [
                        "git",
                        "update-ref",
                        "-d",
                        f"refs/heads/{item['name']}",
                        item["head"],
                    ],
                    cwd=self.root,
                )
                if item["name"] in _branches(self.root):
                    raise RuntimeError("Local branch removal postcondition failed")
            else:
                _delete_remote(self.root, item["name"], item["head"])
            if item["state"] == "eligible":
                item.update(
                    state="removed",
                    reason="Confirmed removal of the frozen merged target",
                )
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            item.update(state="failed", reason=str(error))
            self.report["errors"].append(
                {"kind": item["kind"], "name": item["name"], "error": str(error)}
            )
        logger.info(
            "Repository cleanup result state=%s kind=%s name=%r reason=%s",
            item["state"],
            item["kind"],
            item["name"],
            item["reason"],
        )

    def run(self) -> dict:
        self.inventory()
        if self.execute:
            with exclusive_file_lock(
                self.common / "repository-cleanup.lock", "Repository cleanup"
            ):
                for item in self.report["items"]:
                    if item["state"] == "eligible":
                        if self.report["errors"]:
                            item.update(
                                state="skipped",
                                reason="An earlier failure stopped this cleanup pass",
                            )
                        else:
                            self.mutate(item)
        counts = Counter(item["state"] for item in self.report["items"])
        self.report["summary"] = {
            state: counts[state]
            for state in ("eligible", "skipped", "removed", "failed")
        }
        return self.report


def cleanup_repository(
    repository_path: str,
    *,
    execute: bool = False,
    force: bool = False,
    delete_remote: bool = False,
) -> dict:
    return Cleanup(
        repository_path, execute=execute, force=force, delete_remote=delete_remote
    ).run()
