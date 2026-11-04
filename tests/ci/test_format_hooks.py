from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HAS_PRE_COMMIT = importlib.util.find_spec("pre_commit") is not None


@unittest.skipUnless(
    HAS_PRE_COMMIT,
    "Formatting boundary checks require the isolated CI tools interpreter",
)
class FormattingHookTests(unittest.TestCase):
    def setUp(self) -> None:
        import yaml

        temporary = tempfile.TemporaryDirectory(prefix="agent-smith-format-hooks-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("GIT_")
        }
        self.env.update(
            PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            PRE_COMMIT_HOME=str(self.repo / "pre-commit-cache"),
        )
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Formatting fixture")
        self.git("config", "user.email", "formatting@example.invalid")
        for name in (
            ".pre-commit-config.yaml",
            ".editorconfig",
            "services/client/.prettierrc.json",
            "services/client/.prettierignore",
        ):
            self.write(name, (ROOT / name).read_text())
        self.write(
            ".gitignore",
            "services/client/node_modules\npre-commit-cache/\ncommands/\ngithub-output\n",
        )
        self.write("legacy.py", "legacy={ 'value':1}\n")
        self.write("services/client/legacy.ts", 'export const legacy={value:"old"}\n')
        self.write("rename me.py", "ready = 1\n")
        self.write("delete me.py", "delete={ 'value':1}\n")
        self.write("services/client/rename me.ts", "export const ready = 1;\n")
        self.write(
            "services/client/delete me.ts", 'export const remove={value:"old"}\n'
        )
        self.base = self.commit()
        self.modules = self.repo / "services/client/node_modules"
        self.modules.symlink_to(
            ROOT / "services/client/node_modules", target_is_directory=True
        )
        workflow = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())
        self.preflight = next(
            step["run"]
            for step in workflow["jobs"]["formatting"]["steps"]
            if step.get("id") == "snapshot"
        )

    def write(self, name: str, content: str) -> None:
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()

    def commit(self) -> str:
        self.git("add", "--all")
        self.git("commit", "-qm", "Formatting fixture")
        return self.git("rev-parse", "HEAD")

    def hook(
        self, name: str, head: str, *, base: str | None = None, env: dict | None = None
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pre_commit",
                "run",
                name,
                "--from-ref",
                base or self.base,
                "--to-ref",
                head,
                "--show-diff-on-failure",
            ],
            cwd=self.repo,
            env=env or self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def snapshot(self, base: str, head: str) -> subprocess.CompletedProcess:
        output = self.repo / "github-output"
        output.write_text("")
        return subprocess.run(
            ["bash", "-c", self.preflight],
            cwd=self.repo,
            env={
                **self.env,
                "BASE_SHA": base,
                "HEAD_SHA": head,
                "GITHUB_OUTPUT": str(output),
            },
            capture_output=True,
            text=True,
            timeout=20,
        )

    def assert_passed(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_hooks_check_changed_files_and_leave_legacy_files_alone(self) -> None:
        self.write("new.py", 'value = {"value": 1}\n')
        self.write(
            "services/client/new.ts", "export const value = { value: 'ready' };\n"
        )
        self.write("services/client/dist/generated.ts", 'generated={value:"raw"}\n')
        head = self.commit()
        self.assert_passed(self.snapshot(self.base, head))
        for hook in ("python-format", "frontend-format"):
            with self.subTest(hook=hook):
                self.assert_passed(self.hook(hook, head))
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_malformed_changed_files_fail_without_rewriting_them(self) -> None:
        files = {
            "new.py": "value={ 'value':1}\n",
            "services/client/new.ts": 'export const value={value:"ready"}\n',
        }
        for name, content in files.items():
            self.write(name, content)
        head = self.commit()
        for hook in ("python-format", "frontend-format"):
            with self.subTest(hook=hook):
                result = self.hook(hook, head)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, content in files.items():
            self.assertEqual((self.repo / name).read_text(), content)

    def test_missing_ruff_fails_instead_of_skipping_python(self) -> None:
        self.write("new.py", "value = 1\n")
        head = self.commit()
        command = self.repo / "commands/python"
        command.parent.mkdir()
        command.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -S "$@"\n')
        command.chmod(0o755)
        result = self.hook(
            "python-format",
            head,
            env={
                **self.env,
                "PATH": str(command.parent) + os.pathsep + self.env["PATH"],
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No module named ruff", result.stdout + result.stderr)

    def test_missing_prettier_fails_instead_of_skipping_frontend(self) -> None:
        self.write("services/client/new.ts", "export const value = 1;\n")
        head = self.commit()
        self.modules.unlink()
        result = self.hook("frontend-format", head)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("not found", result.stdout + result.stderr)

    def test_renamed_deleted_and_unusual_filenames_use_upstream_selection(self) -> None:
        self.git("mv", "--", "rename me.py", "-leading [name]\nfile.py")
        self.git(
            "mv",
            "--",
            "services/client/rename me.ts",
            "services/client/space [name]\nfile.ts",
        )
        self.git("rm", "--", "delete me.py", "services/client/delete me.ts")
        head = self.commit()
        for hook in ("python-format", "frontend-format"):
            with self.subTest(hook=hook):
                self.assert_passed(self.hook(hook, head))

    def test_diverged_frozen_refs_use_the_verified_merge_base(self) -> None:
        self.write("base-only.py", "base={ 'unformatted':1}\n")
        advanced_base = self.commit()
        self.git("checkout", "-qb", "feature", self.base)
        self.write("new.py", "value = 1\n")
        head = self.commit()
        self.assert_passed(self.snapshot(advanced_base, head))
        self.assertEqual(
            (self.repo / "github-output").read_text(), f"merge_base={self.base}\n"
        )
        self.assert_passed(self.hook("python-format", head, base=self.base))

    def test_missing_malformed_or_mismatched_refs_fail_before_hooks(self) -> None:
        for base, head in (
            ("a" * 40, self.base),
            ("0" * 40, self.base),
            ("not-a-commit", self.base),
            (self.base, "b" * 40),
        ):
            with self.subTest(base=base, head=head):
                result = self.snapshot(base, head)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.repo / "github-output").read_text(), "")
        self.write("new.py", "value = 1\n")
        self.commit()
        result = self.snapshot(self.base, self.base)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checkout does not match", result.stderr)

    def test_unrelated_frozen_histories_fail_without_a_selector_fallback(self) -> None:
        self.git("checkout", "--orphan", "disconnected")
        self.write("orphan.py", "value = 1\n")
        head = self.commit()
        result = self.snapshot(self.base, head)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must share a merge base", result.stderr)
        self.assertEqual((self.repo / "github-output").read_text(), "")


if __name__ == "__main__":
    unittest.main()
