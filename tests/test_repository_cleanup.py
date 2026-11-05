from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

import pytest

from scripts.shared import repository_cleanup as cleanup


REPOSITORY = "example/cleanup-fixture"


def test_requested_linked_repository_checkout_is_protected(repository, github):
    path, head = repository.worktree()
    github.merged(head)
    report = cleanup.cleanup_repository(str(path), execute=True, force=True)
    assert path.is_dir() and repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "skipped"


@pytest.mark.parametrize("slurped", [False, True])
def test_unpublished_commit_422_is_skipped_for_real_gh_pagination(
    repository, github, monkeypatch, slurped
):
    path, head = repository.worktree()
    response = {"status": "422", "message": f"No commit found for SHA: {head}"}

    def github_with_local_commit(argv, *, cwd):
        if argv[0] == "gh" and any("/commits/" in arg for arg in argv):
            raise cleanup.CommandError(
                "gh", 1, json.dumps([response] if slurped else response)
            )
        return github(argv, cwd=cwd)

    monkeypatch.setattr(cleanup, "_run", github_with_local_commit)
    report = run_cleanup(repository, execute=True, force=True)
    assert path.is_dir() and repository.has_ref("feature/done")
    assert not report["errors"]
    assert item_for(report, "worktree", path)["state"] == "skipped"


class GitRepository:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        self.git("init", "--initial-branch=main")
        self.git("config", "user.name", "Cleanup Test")
        self.git("config", "user.email", "cleanup@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("remote", "add", "origin", f"https://github.com/{REPOSITORY}.git")
        self.commit(root, "initial")

    def git(self, *arguments: str, cwd: Path | None = None) -> str:
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        environment.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
        )
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd or self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return result.stdout

    def commit(self, checkout: Path, message: str) -> str:
        (checkout / "tracked.txt").write_text(message + "\n")
        self.git("add", "tracked.txt", cwd=checkout)
        self.git("commit", "-m", message, cwd=checkout)
        return self.git("rev-parse", "HEAD", cwd=checkout).strip()

    def worktree(
        self, branch: str = "feature/done", *, name: str = "linked checkout"
    ) -> tuple[Path, str]:
        path = self.root.parent / name
        self.git("worktree", "add", "-b", branch, str(path), "main")
        return path, self.commit(path, branch)

    def refs(self) -> str:
        return self.git("for-each-ref", "--format=%(refname)%00%(objectname)")

    def has_ref(self, branch: str) -> bool:
        return f"refs/heads/{branch}\0" in self.refs()


class GitHubBoundary:
    def __init__(self, original_run: Callable):
        self.original_run = original_run
        self.pulls: list[dict] = []
        self.commit_pulls: dict[str, list[dict]] = {}
        self.default = "main"
        self.list_reads = 0
        self.list_response: str | None = None
        self.failure: Exception | None = None
        self.before_list: Callable[[], None] | None = None
        self.before_git: Callable[[list[str], Path], None] | None = None
        self.identity = REPOSITORY

    def merged(
        self, head: str, *, branch: str = "feature/done", number: int = 1, **changes
    ) -> dict:
        pull = {
            "number": number,
            "url": f"https://api.github.com/repos/{REPOSITORY}/pulls/{number}",
            "html_url": f"https://github.com/{REPOSITORY}/pull/{number}",
            "state": "closed",
            "merged_at": "2026-11-01T12:00:00Z",
            "merge_commit_sha": head,
            "head": {"sha": head, "ref": branch, "repo": {"full_name": REPOSITORY}},
            "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
            **changes,
        }
        self.pulls.append(pull)
        self.commit_pulls.setdefault(head, []).append(pull)
        return pull

    def __call__(self, argv: list[str], *, cwd: Path) -> str:
        if argv[0] == "gh":
            if self.failure:
                raise self.failure
            if argv[1:3] == ["repo", "view"]:
                return json.dumps(
                    {
                        "nameWithOwner": self.identity,
                        "defaultBranchRef": {"name": self.default},
                    }
                )
            endpoint = next((value for value in argv if value.startswith("repos/")), "")
            if "/commits/" in endpoint and "/pulls" in endpoint:
                head = endpoint.split("/commits/", 1)[1].split("/", 1)[0]
                pulls = self.commit_pulls.get(head, [])
            elif endpoint.startswith(f"repos/{REPOSITORY}/pulls"):
                self.list_reads += 1
                if self.before_list:
                    self.before_list()
                if self.list_response is not None:
                    return self.list_response
                pulls = self.pulls
            else:
                raise AssertionError(f"Unexpected GitHub request: {argv!r}")
            return json.dumps([pulls] if "--slurp" in argv else pulls)
        assert argv[0] == "git", f"Unexpected external command: {argv!r}"
        if self.before_git:
            self.before_git(argv, cwd)
        assert not any(
            argument.startswith(("https://", "git@github.com:")) for argument in argv
        ), "Tests must not contact GitHub"
        assert not ("fetch" in argv and "origin" in argv), (
            "Tests must not fetch their GitHub origin"
        )
        assert not (
            any(command in argv for command in ["push", "ls-remote"])
            and "origin" in argv
        ), "Local cleanup must not contact its configured GitHub origin"
        return self.original_run(argv, cwd=cwd)


@pytest.fixture
def repository(tmp_path: Path) -> GitRepository:
    return GitRepository(tmp_path / "repository")


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> GitHubBoundary:
    boundary = GitHubBoundary(cleanup._run)
    monkeypatch.setattr(cleanup, "_run", boundary)
    monkeypatch.setattr(cleanup, "_active_paths", lambda: set())
    return boundary


def run_cleanup(repository: GitRepository, **options) -> dict:
    report = cleanup.cleanup_repository(str(repository.root), **options)
    assert isinstance(report["items"], list)
    assert isinstance(report["summary"], dict)
    for item in report["items"]:
        assert {"kind", "name", "head", "state", "reason", "pr"} <= item.keys()
        assert item["state"] in {"eligible", "skipped", "removed", "failed"}
    return report


def item_for(report: dict, kind: str, name: str | Path) -> dict:
    matches = [
        item
        for item in report["items"]
        if item["kind"] == kind and item["name"] == str(name)
    ]
    assert len(matches) == 1, report
    return matches[0]


def assert_fails_closed(repository: GitRepository, action: Callable[[], dict]) -> None:
    before = repository.refs()
    try:
        report = action()
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError):
        pass
    else:
        assert report.get("errors") or any(
            item["state"] == "failed" for item in report["items"]
        ), report
    assert repository.refs() == before


def test_preview_reports_exact_merged_heads_without_changing_refs_or_worktrees(
    repository, github
):
    path, head = repository.worktree()
    github.merged(head)
    refs = repository.refs()
    registered = repository.git("worktree", "list", "--porcelain", "-z")

    report = run_cleanup(repository)

    assert item_for(report, "worktree", path)["state"] == "eligible"
    assert item_for(report, "local_branch", "feature/done")["state"] == "eligible"
    assert repository.refs() == refs
    assert repository.git("worktree", "list", "--porcelain", "-z") == registered
    assert path.is_dir()


def test_execute_removes_worktree_and_branch_proven_merged_even_after_squash(
    repository, github
):
    path, head = repository.worktree()
    github.merged(head)
    assert repository.git("rev-list", "main..feature/done").strip() == head

    report = run_cleanup(repository, execute=True)

    assert not path.exists()
    assert not repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "removed"
    assert item_for(report, "local_branch", "feature/done")["state"] == "removed"
    assert repository.has_ref("main")
    assert repository.git("branch", "--show-current").strip() == "main"


def test_open_same_branch_pr_vetoes_historical_merge_even_with_force(
    repository, github
):
    path, head = repository.worktree()
    github.merged(head)
    github.merged(head, number=2, state="open", merged_at=None, merge_commit_sha=None)

    report = run_cleanup(repository, execute=True, force=True)

    assert path.is_dir() and repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "skipped"
    assert "open" in item_for(report, "worktree", path)["reason"].lower()


def test_closed_unmerged_pr_never_authorizes_cleanup(repository, github):
    path, head = repository.worktree()
    github.merged(head, merged_at=None, merge_commit_sha=None)

    report = run_cleanup(repository, execute=True, force=True)

    assert path.is_dir() and repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "skipped"


def test_new_commits_on_reused_branch_are_preserved(repository, github):
    path, old_head = repository.worktree()
    github.merged(old_head)
    new_head = repository.commit(path, "new work after merge")

    report = run_cleanup(repository, execute=True, force=True)

    assert path.is_dir()
    assert repository.git("rev-parse", "feature/done").strip() == new_head
    assert item_for(report, "local_branch", "feature/done")["state"] == "skipped"


def test_renamed_branch_resolves_exact_commit_associated_merged_pr(repository, github):
    path, head = repository.worktree()
    github.merged(head)
    repository.git("branch", "-m", "feature/done", "feature/renamed")

    report = run_cleanup(repository, execute=True)

    assert not path.exists() and not repository.has_ref("feature/renamed")
    assert item_for(report, "local_branch", "feature/renamed")["pr"]


def test_detached_worktree_resolves_merged_pr_by_commit(repository, github):
    original, head = repository.worktree()
    github.merged(head)
    repository.git("worktree", "remove", str(original))
    repository.git("branch", "-D", "feature/done")
    detached = repository.root.parent / "detached checkout"
    repository.git("worktree", "add", "--detach", str(detached), head)

    report = run_cleanup(repository, execute=True)

    assert not detached.exists()
    assert item_for(report, "worktree", detached)["state"] == "removed"


def test_detached_exact_pr_merge_result_is_proven_by_commit_association(
    repository, github
):
    original, head = repository.worktree()
    repository.git("merge", "--no-ff", "feature/done", "-m", "merged feature")
    merged = repository.git("rev-parse", "HEAD").strip()
    pull = github.merged(head, merge_commit_sha=merged)
    github.commit_pulls[merged] = [pull]
    repository.git("worktree", "remove", str(original))
    repository.git("branch", "-D", "feature/done")
    detached = repository.root.parent / "detached merged result"
    repository.git("worktree", "add", "--detach", str(detached), merged)

    report = run_cleanup(repository, execute=True)

    assert not detached.exists()
    assert item_for(report, "worktree", detached)["state"] == "removed"


def test_new_unpublished_branch_seeded_at_another_pr_merge_result_is_preserved(
    repository, github
):
    original, head = repository.worktree()
    repository.git("merge", "--no-ff", "feature/done", "-m", "merged feature")
    merged = repository.git("rev-parse", "HEAD").strip()
    pull = github.merged(head, merge_commit_sha=merged)
    github.commit_pulls[merged] = [pull]
    repository.git("worktree", "remove", str(original))
    repository.git("branch", "-D", "feature/done")
    snapshot = repository.root.parent / "unpublished snapshot"
    repository.git(
        "worktree", "add", "-b", "feature/new-snapshot", str(snapshot), merged
    )

    report = run_cleanup(repository, execute=True, force=True)

    assert snapshot.is_dir() and repository.has_ref("feature/new-snapshot")
    assert item_for(report, "worktree", snapshot)["state"] == "skipped"


@pytest.mark.parametrize("branch", ["master", "staging", "release"])
def test_protected_and_github_default_branches_survive_force(
    repository, github, branch
):
    path, head = repository.worktree(branch)
    github.default = "release"
    github.merged(head, branch=branch)

    report = run_cleanup(repository, execute=True, force=True)

    assert path.is_dir() and repository.has_ref(branch)
    assert item_for(report, "local_branch", branch)["state"] == "skipped"


def test_current_primary_checkout_and_its_branch_are_preserved(repository, github):
    repository.git("switch", "-c", "feature/current")
    head = repository.commit(repository.root, "primary checkout work")
    github.merged(head, branch="feature/current")

    report = run_cleanup(repository, execute=True, force=True)

    assert repository.root.is_dir() and repository.has_ref("feature/current")
    assert item_for(report, "worktree", repository.root)["state"] == "skipped"
    assert item_for(report, "local_branch", "feature/current")["state"] == "skipped"


@pytest.mark.parametrize("force", [False, True])
def test_force_only_controls_dirty_merged_worktree_removal(repository, github, force):
    path, head = repository.worktree()
    github.merged(head)
    (path / "tracked.txt").write_text("uncommitted tracked work\n")
    (path / "untracked.txt").write_text("uncommitted new work\n")

    report = run_cleanup(repository, execute=True, force=force)

    assert path.exists() is not force
    assert repository.has_ref("feature/done") is not force
    assert item_for(report, "worktree", path)["state"] == (
        "removed" if force else "skipped"
    )


def test_active_descendant_path_blocks_worktree_and_branch_even_with_force(
    repository, github, monkeypatch
):
    path, head = repository.worktree()
    github.merged(head)
    active = path / "nested" / "cwd"
    monkeypatch.setattr(cleanup, "_active_paths", lambda: {active})

    report = run_cleanup(repository, execute=True, force=True)

    assert path.is_dir() and repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "skipped"
    assert "active" in item_for(report, "worktree", path)["reason"].lower()


def test_locked_worktree_survives_force(repository, github):
    path, head = repository.worktree()
    github.merged(head)
    repository.git(
        "worktree",
        "lock",
        "--reason",
        "another operation owns this checkout",
        str(path),
    )

    report = run_cleanup(repository, execute=True, force=True)

    assert path.is_dir() and repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "skipped"
    assert "lock" in item_for(report, "worktree", path)["reason"].lower()


def test_common_repository_lock_fails_immediately_without_mutation(repository, github):
    path, head = repository.worktree()
    github.merged(head)
    lock_path = repository.root / ".git" / "repository-cleanup.lock"

    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        started = time.monotonic()
        assert_fails_closed(
            repository, lambda: run_cleanup(repository, execute=True, force=True)
        )
        assert time.monotonic() - started < 2, "Cleanup lock acquisition must not wait"

    assert path.is_dir() and repository.has_ref("feature/done")


def test_symlinked_registered_worktree_is_never_followed_or_deleted(repository, github):
    path, head = repository.worktree()
    github.merged(head)
    relocated = path.with_name("valuable relocated checkout")
    path.rename(relocated)
    path.symlink_to(relocated, target_is_directory=True)

    report = run_cleanup(repository, execute=True, force=True)

    assert path.is_symlink() and relocated.is_dir()
    assert repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "skipped"


def test_retained_primary_dependency_symlink_protects_merged_worktree(
    repository, github
):
    path, head = repository.worktree()
    github.merged(head)
    dependency = path / ".ci-app-venv"
    dependency.mkdir()
    marker = dependency / "runtime-must-survive"
    marker.write_text("retained dependency\n")
    canonical_link = repository.root / ".venv"
    canonical_link.symlink_to(dependency, target_is_directory=True)

    report = run_cleanup(repository, execute=True, force=True)

    assert canonical_link.is_dir() and marker.is_file()
    assert path.is_dir() and repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "skipped"


@pytest.mark.parametrize(
    "response",
    [
        "{not-json",
        '{"unexpected": []}',
        '[[{"number": 1, "state": "closed", "merged_at": "2026-11-01"}]]',
    ],
)
def test_malformed_github_evidence_fails_closed(repository, github, response):
    path, head = repository.worktree()
    github.merged(head)
    github.list_response = response

    assert_fails_closed(
        repository, lambda: run_cleanup(repository, execute=True, force=True)
    )

    assert path.is_dir()


def test_github_timeout_keeps_all_refs_and_worktrees(repository, github):
    path, head = repository.worktree()
    github.merged(head)
    github.failure = subprocess.TimeoutExpired(["gh", "api"], timeout=30)

    assert_fails_closed(
        repository, lambda: run_cleanup(repository, execute=True, force=True)
    )

    assert path.is_dir()


def test_origin_identity_mismatch_fails_before_deletion(repository, github):
    path, head = repository.worktree()
    github.merged(head)
    github.identity = "unrelated/other-repository"

    assert_fails_closed(
        repository, lambda: run_cleanup(repository, execute=True, force=True)
    )

    assert path.is_dir()


@pytest.mark.parametrize("side", ["head", "base"])
def test_foreign_repository_pr_evidence_cannot_authorize_deletion(
    repository, github, side
):
    path, head = repository.worktree()
    pull = github.merged(head)
    pull[side]["repo"]["full_name"] = "unrelated/other-repository"

    try:
        report = run_cleanup(repository, execute=True, force=True)
    except (RuntimeError, ValueError):
        pass
    else:
        assert item_for(report, "worktree", path)["state"] in {"skipped", "failed"}

    assert path.is_dir() and repository.has_ref("feature/done")


def test_unavailable_process_inventory_fails_closed_even_with_force(
    repository, github, monkeypatch
):
    path, head = repository.worktree()
    github.merged(head)

    def unavailable():
        raise RuntimeError("process inventory unavailable")

    monkeypatch.setattr(cleanup, "_active_paths", unavailable)

    assert_fails_closed(
        repository, lambda: run_cleanup(repository, execute=True, force=True)
    )

    assert path.is_dir()


def test_pr_reopened_between_inventory_and_execution_is_preserved(repository, github):
    path, head = repository.worktree()
    pull = github.merged(head)

    def reopen():
        if github.list_reads > 1:
            pull.update(state="open", merged_at=None, merge_commit_sha=None)

    github.before_list = reopen

    report = run_cleanup(repository, execute=True, force=True)

    assert path.is_dir() and repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] in {"skipped", "failed"}


def test_github_head_drift_is_rejected_even_when_new_head_contains_snapshot(
    repository, github
):
    path, head = repository.worktree()
    pull = github.merged(head)
    descendant = repository.git(
        "commit-tree", f"{head}^{{tree}}", "-p", head, "-m", "new merged head"
    ).strip()

    def change_github_head():
        if github.list_reads > 1:
            pull["head"]["sha"] = descendant

    github.before_list = change_github_head

    report = run_cleanup(repository, execute=True, force=True)

    assert path.is_dir()
    assert repository.git("rev-parse", "feature/done").strip() == head
    assert item_for(report, "worktree", path)["state"] in {"skipped", "failed"}


def test_live_ref_drift_blocks_worktree_deletion(repository, github, monkeypatch):
    path, head = repository.worktree()
    github.merged(head)
    replacement = repository.commit(repository.root, "independent new revision")
    inspections = 0

    def inspect_paths():
        nonlocal inspections
        inspections += 1
        if inspections > 1:
            repository.git("update-ref", "refs/heads/feature/done", replacement)
        return set()

    monkeypatch.setattr(cleanup, "_active_paths", inspect_paths)

    run_cleanup(repository, execute=True, force=True)

    assert path.is_dir()
    assert repository.git("rev-parse", "feature/done").strip() == replacement


def test_local_branch_compare_and_delete_preserves_a_concurrent_new_tip(
    repository, github
):
    path, head = repository.worktree()
    github.merged(head)
    repository.git("worktree", "remove", str(path))
    replacement = repository.commit(repository.root, "concurrent branch revision")
    raced = False

    def change_ref_before_delete(argv, cwd):
        nonlocal raced
        if not raced and (
            "update-ref" in argv
            and "-d" in argv
            or "branch" in argv
            and any(flag in argv for flag in ["-d", "-D"])
        ):
            raced = True
            repository.git("update-ref", "refs/heads/feature/done", replacement)

    github.before_git = change_ref_before_delete

    report = run_cleanup(repository, execute=True)

    assert raced, "The deletion path must perform an observable atomic ref deletion"
    assert repository.git("rev-parse", "feature/done").strip() == replacement
    assert item_for(report, "local_branch", "feature/done")["state"] in {
        "skipped",
        "failed",
    }


@pytest.mark.parametrize("stale", [False, True])
def test_real_bare_origin_remote_deletion_requires_exact_expected_oid(
    repository, tmp_path, stale
):
    origin = tmp_path / "origin.git"
    repository.git("init", "--bare", str(origin))
    repository.git("remote", "set-url", "origin", str(origin))
    path, expected = repository.worktree()
    repository.git("push", "origin", "feature/done")
    latest = expected
    if stale:
        latest = repository.commit(path, "new remote work")
        repository.git("push", "origin", "feature/done")

    try:
        cleanup._delete_remote(repository.root, "feature/done", expected)
    except (RuntimeError, OSError, subprocess.SubprocessError):
        assert stale, "The matching expected-OID deletion must succeed"

    remaining = repository.git(
        "ls-remote", "--heads", "origin", "refs/heads/feature/done"
    )
    assert remaining.strip() == (f"{latest}\trefs/heads/feature/done" if stale else "")


def test_second_execution_is_idempotent(repository, github):
    path, head = repository.worktree()
    github.merged(head)
    run_cleanup(repository, execute=True)
    refs = repository.refs()

    report = run_cleanup(repository, execute=True)

    assert not path.exists() and repository.refs() == refs
    assert not any(item["state"] in {"removed", "failed"} for item in report["items"])


def test_worktree_paths_with_spaces_and_newlines_round_trip(repository, github):
    path, head = repository.worktree(name="linked checkout\nwith newline")
    github.merged(head)

    report = run_cleanup(repository, execute=True)

    assert not path.exists() and not repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "removed"


def test_deletion_emits_attempt_and_result_logs(repository, github, caplog):
    path, head = repository.worktree()
    github.merged(head)
    caplog.set_level(logging.INFO)

    run_cleanup(repository, execute=True)

    messages = [record.getMessage().lower() for record in caplog.records]
    assert not path.exists()
    assert any("attempt" in message for message in messages)
    assert any(
        any(word in message for word in ["removed", "result", "succeeded"])
        for message in messages
    )


def test_command_runner_ignores_inherited_git_redirects(
    repository, tmp_path, monkeypatch
):
    unrelated = GitRepository(tmp_path / "unrelated")
    monkeypatch.setenv("GIT_DIR", str(unrelated.root / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(unrelated.root))

    actual = cleanup._run(["git", "rev-parse", "--show-toplevel"], cwd=repository.root)

    assert actual.strip() == str(repository.root)


def test_new_retained_dependency_reference_before_execution_preserves_target(
    repository, github, monkeypatch
):
    path, head = repository.worktree()
    github.merged(head)
    dependency = path / ".ci-app-venv"
    dependency.mkdir()
    inspections = 0

    def inspect_paths():
        nonlocal inspections
        inspections += 1
        if inspections > 1 and not (repository.root / ".venv").is_symlink():
            (repository.root / ".venv").symlink_to(dependency, target_is_directory=True)
        return set()

    monkeypatch.setattr(cleanup, "_active_paths", inspect_paths)
    report = run_cleanup(repository, execute=True, force=True)
    assert path.is_dir()
    assert dependency.is_dir()
    assert repository.has_ref("feature/done")
    assert item_for(report, "worktree", path)["state"] == "skipped"


def test_real_remote_lease_rejects_drift_after_the_precheck(
    repository, tmp_path, monkeypatch
):
    origin = tmp_path / "origin.git"
    repository.git("init", "--bare", str(origin))
    repository.git("remote", "set-url", "origin", str(origin))
    path, expected = repository.worktree()
    repository.git("push", "origin", "feature/done")
    replacement = repository.commit(path, "remote revision after preflight")
    repository.git("push", "origin", f"{replacement}:refs/heads/prepared")
    original_run = cleanup._run
    raced = False

    def race_before_push(argv, *, cwd):
        nonlocal raced
        if "push" in argv and not raced:
            raced = True
            repository.git(
                "update-ref",
                "refs/heads/feature/done",
                replacement,
                expected,
                cwd=origin,
            )
        return original_run(argv, cwd=cwd)

    monkeypatch.setattr(cleanup, "_run", race_before_push)
    with pytest.raises(RuntimeError):
        cleanup._delete_remote(repository.root, "feature/done", expected)
    assert raced
    assert (
        repository.git(
            "ls-remote", "--heads", "origin", "refs/heads/feature/done"
        ).strip()
        == f"{replacement}\trefs/heads/feature/done"
    )
