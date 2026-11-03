from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from copy import deepcopy
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from scripts.shared.atomic_json import atomic_write_json, exclusive_file_lock
from scripts.shared.claude_memory_redaction import redact_for_capture
from scripts.shared.claude_repo_scope import resolve_repo
from scripts.shared.claude_transcript import Cursor, TranscriptError, fragment_to_dict, read_page

MAX_OUTPUT_BYTES = 12 * 1024
MAX_SOURCES = 128
MAX_STATE_BYTES = 512 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024
_AGENT_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_PATH = re.compile(r'''"(/[^"\n]+)"|'(/[^'\n]+)'|(/[A-Za-z0-9_@+.,~/-]+)''')


class CaptureError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _session_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise CaptureError("invalid_session_id") from None


def _memory_ids(values: list[str]) -> list[str]:
    if not isinstance(values, list) or len(values) > 3:
        raise CaptureError("invalid_memory_ids")
    try:
        return [str(uuid.UUID(value)) for value in values]
    except (ValueError, AttributeError, TypeError):
        raise CaptureError("invalid_memory_ids") from None


def _cursor(value: object) -> Cursor:
    if not isinstance(value, dict) or set(value) != {"offset", "block_index", "char_offset"}:
        raise CaptureError("invalid_checkpoint")
    if any(type(number) is not int or number < 0 for number in value.values()):
        raise CaptureError("invalid_checkpoint")
    return Cursor(**value)


def _identity(path: Path) -> dict[str, int]:
    info = path.stat()
    if not path.is_file():
        raise CaptureError("source_is_not_a_file")
    return {"device": info.st_dev, "inode": info.st_ino}


def _range_hash(path: Path, start: int, end: int) -> str:
    if start < 0 or end < start or end - start > 16 * 1024 * 1024 + MAX_RECORD_BYTES:
        raise CaptureError("invalid_snapshot_range")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        stream.seek(start)
        remaining = end - start
        while remaining:
            chunk = stream.read(min(remaining, 65536))
            if not chunk:
                raise CaptureError("source_truncated")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


class CaptureStore:
    def __init__(
        self,
        transcripts_root: Path,
        state_root: Path,
        *,
        repo_resolver: Callable[[str], dict[str, str] | None] | None = None,
        allowed_repo_roots: tuple[Path, ...] | None = None,
        clock: Callable[[], float] = time.monotonic,
        operation_timeout: float = 5.0,
    ) -> None:
        self.transcripts_root = Path(transcripts_root).resolve()
        self.state_root = Path(state_root)
        roots = (Path.home().resolve(),) if allowed_repo_roots is None else allowed_repo_roots
        self.repo_resolver = repo_resolver or (lambda path: resolve_repo(path, roots))
        if operation_timeout <= 0:
            raise ValueError("Capture operation timeout must be positive")
        self.clock = clock
        self.operation_timeout = operation_timeout

    def _member(self, path: Path) -> Path:
        if not path.is_absolute():
            raise CaptureError("source_path_must_be_absolute")
        lexical = Path(path)
        if not lexical.is_relative_to(self.transcripts_root) or ".." in lexical.parts:
            raise CaptureError("source_outside_transcripts_root")
        relative = lexical.relative_to(self.transcripts_root)
        current = self.transcripts_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise CaptureError("source_symlink_rejected")
        resolved = lexical.resolve(strict=True)
        if not resolved.is_relative_to(self.transcripts_root):
            raise CaptureError("source_outside_transcripts_root")
        if not resolved.is_file():
            raise CaptureError("source_is_not_a_file")
        return resolved

    def _parent(self, session_id: str, supplied: str) -> Path:
        path = self._member(Path(supplied).expanduser())
        if path.name == f"{session_id}.jsonl":
            if len(path.relative_to(self.transcripts_root).parts) != 2:
                raise CaptureError("invalid_parent_transcript_location")
            return path
        for directory in path.parents:
            if directory == self.transcripts_root:
                break
            if directory.name == session_id:
                return self._parent(session_id, str(directory.parent / f"{session_id}.jsonl"))
        raise CaptureError("transcript_session_path_mismatch")

    def _sources(self, parent: Path) -> list[Path]:
        directory = parent.with_suffix("") / "subagents"
        children = sorted(directory.glob("agent-*.jsonl"))
        workflow_agents = sorted(directory.glob("workflows/*/agent-*.jsonl"))
        journals = sorted(directory.glob("workflows/*/journal.jsonl"))
        paths = [parent, *children, *workflow_agents, *journals]
        if len(paths) > MAX_SOURCES:
            raise CaptureError("too_many_session_sources")
        return [self._member(path) for path in paths]

    def _workflow_agents(self, path: Path, session_id: str) -> frozenset[str]:
        verified: set[str] = set()
        for child in sorted(path.parent.glob("agent-*.jsonl")):
            child = self._member(child)
            agent_id = child.stem.removeprefix("agent-")
            if not _AGENT_ID.fullmatch(agent_id):
                raise CaptureError("invalid_workflow_agent_id")
            with child.open("rb") as stream:
                row_bytes = stream.readline(MAX_RECORD_BYTES + 1)
            if not row_bytes.endswith(b"\n") or len(row_bytes) > MAX_RECORD_BYTES:
                raise CaptureError("workflow_agent_header_incomplete")
            try:
                row = json.loads(row_bytes)
            except (ValueError, UnicodeError):
                raise CaptureError("workflow_agent_header_invalid") from None
            if not isinstance(row, dict) or row.get("sessionId") != session_id:
                raise CaptureError("workflow_agent_session_mismatch")
            if row.get("agentId") not in (None, agent_id):
                raise CaptureError("workflow_agent_id_mismatch")
            verified.add(agent_id)
        return frozenset(verified)

    def _load(self, session_id: str) -> dict[str, Any]:
        path = self.state_root / f"{session_id}.json"
        if path.is_symlink():
            raise CaptureError("state_symlink_rejected")
        if not path.exists():
            return {"version": 1, "session_id": session_id, "files": {}}
        if path.stat().st_size > MAX_STATE_BYTES:
            raise CaptureError("capture_state_too_large")
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            raise CaptureError("invalid_capture_state") from None
        if (not isinstance(state, dict) or state.get("version") != 1
                or state.get("session_id") != session_id or not isinstance(state.get("files"), dict)):
            raise CaptureError("invalid_capture_state")
        if len(state["files"]) > MAX_SOURCES or state.get("parent_path") is not None and not isinstance(state["parent_path"], str):
            raise CaptureError("invalid_capture_state")
        for key, checkpoint in state["files"].items():
            if not isinstance(key, str) or not isinstance(checkpoint, dict):
                raise CaptureError("invalid_checkpoint")
            _cursor(checkpoint.get("cursor"))
            self._validate_identity(checkpoint.get("identity"))
            self._validate_fence(checkpoint.get("fence"))
        self._validate_scopes(state.get("session_scopes", []))
        if state.get("pending") is not None:
            pending = state["pending"]
            if not isinstance(pending, dict):
                raise CaptureError("invalid_pending_receipt")
            if not isinstance(pending.get("source"), str) or not isinstance(pending.get("receipt"), str):
                raise CaptureError("invalid_pending_receipt")
            if not isinstance(state.get("parent_path"), str) or not re.fullmatch(r"[a-f0-9]{32}", pending["receipt"]):
                raise CaptureError("invalid_pending_receipt")
            _cursor(pending.get("start_cursor"))
            _cursor(pending.get("next_cursor"))
            self._validate_identity(pending.get("identity"))
            for key in ("scan_start", "scan_end", "snapshot_end"):
                if type(pending.get(key)) is not int or pending[key] < 0:
                    raise CaptureError("invalid_pending_receipt")
            if not re.fullmatch(r"[a-f0-9]{64}", str(pending.get("source_hash", ""))):
                raise CaptureError("invalid_pending_receipt")
            if not re.fullmatch(r"[a-f0-9]{64}", str(pending.get("context_hash", ""))):
                raise CaptureError("invalid_pending_receipt")
            if not (pending["scan_start"] == pending["start_cursor"]["offset"]
                    <= pending["next_cursor"]["offset"] <= pending["scan_end"] <= pending["snapshot_end"]):
                raise CaptureError("invalid_pending_receipt")
        if state.get("last_ack") is not None:
            previous = state["last_ack"]
            if (not isinstance(previous, dict) or not isinstance(previous.get("receipt"), str)
                    or not isinstance(previous.get("outcome"), str)
                    or previous["outcome"] not in {"saved", "duplicate", "nothing_to_save"}
                    or not isinstance(previous.get("memory_ids"), list)
                    or len(previous["memory_ids"]) > 3):
                raise CaptureError("invalid_acknowledgement_state")
            _memory_ids(previous["memory_ids"])
        if state.get("current_capture") is not None:
            current = state["current_capture"]
            if (not isinstance(current, dict) or current.get("evidence_kind") != "hook_last_assistant_message"
                    or not _memory_ids(current.get("memory_ids"))):
                raise CaptureError("invalid_current_capture_state")
        return state

    @staticmethod
    def _validate_identity(value: object) -> None:
        if (not isinstance(value, dict) or set(value) != {"device", "inode"}
                or any(type(item) is not int or item < 0 for item in value.values())):
            raise CaptureError("invalid_source_identity")

    @staticmethod
    def _validate_fence(value: object) -> None:
        if (not isinstance(value, dict)
                or any(type(value.get(key)) is not int or value[key] < 0 for key in ("start", "end"))
                or value["end"] < value["start"]
                or not re.fullmatch(r"[a-f0-9]{64}", str(value.get("hash", "")))):
            raise CaptureError("invalid_checkpoint_fence")

    @staticmethod
    def _validate_scopes(scopes: object) -> None:
        if not isinstance(scopes, list) or len(scopes) > 16:
            raise CaptureError("invalid_scope_snapshot")
        for scope in scopes:
            if (not isinstance(scope, dict) or not {"repo", "root"}.issubset(scope)
                    or any(not isinstance(value, str) or len(value) > 8192 for value in scope.values())):
                raise CaptureError("invalid_scope_snapshot")

    def _save(self, state: dict[str, Any]) -> None:
        atomic_write_json(self.state_root / f"{state['session_id']}.json", state)

    def _operation(self, session_id: str, stage: str, action: Callable[[dict], dict], *, record: bool = True) -> dict:
        try:
            session_id = _session_id(session_id)
            with exclusive_file_lock(self.state_root / f"{session_id}.lock", "Memory capture"):
                state = self._load(session_id)
                candidate = deepcopy(state)
                started = self.clock()
                try:
                    result = action(candidate)
                    if self.clock() - started > self.operation_timeout:
                        raise CaptureError("helper_time_budget_exceeded")
                    if record:
                        candidate["last_run"] = {key: value for key, value in result.items()
                                                 if key in {"status", "stage", "error_code", "receipt", "memory_ids", "remaining"}}
                        self._save(candidate)
                    return result
                except (CaptureError, TranscriptError, OSError, ValueError) as exc:
                    result = {"status": "error", "stage": stage,
                              "error_code": exc.code if isinstance(exc, CaptureError) else type(exc).__name__}
                    if record:
                        state["last_run"] = result
                        self._save(state)
                    return result
        except RuntimeError as exc:
            if str(exc).startswith("Memory capture is already running"):
                return {"status": "busy", "stage": stage, "error_code": "capture_locked"}
            raise
        except (CaptureError, OSError, ValueError) as exc:
            return {"status": "error", "stage": stage,
                    "error_code": exc.code if isinstance(exc, CaptureError) else type(exc).__name__}

    def _source_for_receipt(self, state: dict, pending: dict) -> Path:
        parent = self._parent(state["session_id"], state["parent_path"])
        matches = [path for path in self._sources(parent)
                   if str(path.relative_to(self.transcripts_root)) == pending.get("source")]
        if len(matches) != 1:
            raise CaptureError("receipt_source_missing")
        path = matches[0]
        if _identity(path) != pending.get("identity"):
            raise CaptureError("source_replaced")
        if path.stat().st_size < pending["snapshot_end"]:
            raise CaptureError("source_truncated")
        if _range_hash(path, pending["scan_start"], pending["scan_end"]) != pending["source_hash"]:
            raise CaptureError("source_changed_since_read")
        return path

    def _page(self, path: Path, session_id: str, snapshot_end: int, cursor: Cursor):
        journal = path.name == "journal.jsonl"
        with path.open("rb") as stream:
            page = read_page(
                stream, session_id=session_id, snapshot_end=snapshot_end, cursor=cursor,
                output_budget=4096, source_kind="workflow_journal" if journal else "transcript",
                include_sidechain=path.name != f"{session_id}.jsonl",
                workflow_agent_ids=self._workflow_agents(path, session_id) if journal else frozenset(),
                text_transform=redact_for_capture,
            )
        if page.source_hash != _range_hash(path, cursor.offset, page.scan_end):
            raise CaptureError("source_changed_during_read")
        return page

    def _context(self, source_fragments, repo_paths: tuple[str, ...], known_scopes: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
        fragments: list[dict] = []
        repos: dict[str, dict] = {}
        snapshots: dict[str, dict] = {}
        resolved: dict[str, dict | None] = {}
        scope_bytes = 0

        def include(repo: dict, *, current: bool = False) -> str | None:
            nonlocal scope_bytes
            self._validate_scopes([repo])
            repo_id = hashlib.sha256(json.dumps(repo, sort_keys=True).encode()).hexdigest()[:16]
            if len(json.dumps(repo["repo"], ensure_ascii=True).encode("ascii")) > 128:
                return None
            if repo_id not in repos:
                if len(repos) >= 16:
                    raise CaptureError("too_many_repository_scopes")
                bounded = {"id": repo_id, "repo": repo["repo"], "current_page": current}
                if scope_bytes + len(json.dumps(repo, ensure_ascii=True).encode("ascii")) < 2048:
                    bounded.update(repo)
                else:
                    bounded["paths_omitted"] = True
                scope_bytes += len(json.dumps(bounded, ensure_ascii=True).encode("ascii"))
                repos[repo_id] = bounded
                snapshots[repo_id] = repo
            elif current:
                repos[repo_id]["current_page"] = True
            return repo_id

        def resolve(hint: object) -> dict | None:
            if not isinstance(hint, str) or not hint or (hint not in resolved and len(resolved) >= 8):
                return None
            if hint not in resolved:
                resolved[hint] = self.repo_resolver(hint)
            return resolved[hint]

        for scope in known_scopes:
            include(scope)
        for path in repo_paths:
            scope = resolve(path)
            if scope is not None:
                include(scope, current=True)
        for fragment in source_fragments:
            item = fragment_to_dict(fragment)
            raw_text = item["text"]
            hints = [item.get("cwd")]
            hints.extend(next(value for value in match if value) for match in _PATH.findall(raw_text))
            item_repos: dict[str, dict] = {}
            for hint in hints:
                repo = resolve(hint)
                if repo is not None:
                    repo_id = include(repo, current=True)
                    if repo_id is not None:
                        item_repos[repo_id] = repos[repo_id]
            item["verified_repo_ids"] = list(item_repos)
            fragments.append(item)
        return fragments, list(repos.values()), list(snapshots.values())

    def _render(self, state: dict, pending: dict, path: Path) -> dict:
        page = self._page(path, state["session_id"], pending["snapshot_end"], _cursor(pending["start_cursor"]))
        if (asdict(page.next_cursor) != pending["next_cursor"] or page.scan_end != pending["scan_end"]
                or page.source_hash != pending["source_hash"] or _identity(path) != pending["identity"]):
            raise CaptureError("receipt_coverage_changed")
        fragments, repos, scopes = self._context(page.fragments, page.repo_paths, state.get("session_scopes", []))
        context_hash = hashlib.sha256(json.dumps([fragments, repos], sort_keys=True, ensure_ascii=True).encode("ascii")).hexdigest()
        if "context_hash" in pending and context_hash != pending["context_hash"]:
            raise CaptureError("context_changed_since_read")
        pending["context_hash"] = context_hash
        pending["next_scopes"] = scopes
        parent = self._parent(state["session_id"], state["parent_path"])
        remaining = not page.snapshot_complete or path.stat().st_size > pending["snapshot_end"]
        for other in self._sources(parent):
            relative = str(other.relative_to(self.transcripts_root))
            if relative == pending["source"]:
                continue
            checkpoint = state["files"].get(relative)
            offset = _cursor(checkpoint["cursor"]).offset if checkpoint else 0
            remaining = remaining or other.stat().st_size > offset
        result = {
            "status": "ready", "session_id": state["session_id"], "receipt": pending["receipt"],
            "source": pending["source"], "snapshot_end": pending["snapshot_end"],
            "next_cursor": pending["next_cursor"], "source_complete": page.snapshot_complete,
            "pending_tail": page.pending_tail, "remaining": remaining,
            "skipped_records": page.skipped_records, "skipped_blocks": page.skipped_blocks,
            "untrusted_context": fragments, "verified_repos": repos,
        }
        if len(json.dumps(result, ensure_ascii=True).encode("ascii")) > MAX_OUTPUT_BYTES:
            raise CaptureError("context_envelope_too_large")
        return result

    def read(self, session_id: str, transcript_path: str) -> dict:
        def action(state: dict) -> dict:
            parent = self._parent(state["session_id"], transcript_path)
            if state.get("parent_path") not in (None, str(parent)):
                raise CaptureError("session_source_changed")
            state["parent_path"] = str(parent)
            if state.get("pending") is not None:
                pending = state["pending"]
                return self._render(state, pending, self._source_for_receipt(state, pending))
            waiting = False
            sources = self._sources(parent)
            marker = state.get("next_source")
            for index, path in enumerate(sources):
                if str(path.relative_to(self.transcripts_root)) == marker:
                    sources = sources[index:] + sources[:index]
                    break
            for path in sources:
                relative = str(path.relative_to(self.transcripts_root))
                checkpoint = state["files"].get(relative)
                if checkpoint is not None and not isinstance(checkpoint, dict):
                    raise CaptureError("invalid_checkpoint")
                cursor = _cursor(checkpoint["cursor"]) if checkpoint else Cursor()
                identity = _identity(path)
                if checkpoint and identity != checkpoint.get("identity"):
                    raise CaptureError("source_replaced")
                if checkpoint:
                    fence = checkpoint["fence"]
                    if _range_hash(path, fence["start"], fence["end"]) != fence["hash"]:
                        raise CaptureError("acknowledged_source_changed")
                snapshot_end = path.stat().st_size
                if cursor.offset > snapshot_end:
                    raise CaptureError("source_truncated")
                if cursor.offset == snapshot_end and cursor.block_index == 0 and cursor.char_offset == 0:
                    continue
                page = self._page(path, state["session_id"], snapshot_end, cursor)
                if not page.fragments and page.next_cursor == cursor:
                    waiting = True
                    continue
                pending = {
                    "receipt": uuid.uuid4().hex, "source": relative, "identity": identity,
                    "snapshot_end": snapshot_end, "start_cursor": asdict(cursor),
                    "next_cursor": asdict(page.next_cursor), "scan_start": cursor.offset,
                    "scan_end": page.scan_end, "source_hash": page.source_hash,
                }
                result = self._render(state, pending, path)
                state["pending"] = pending
                return result
            if waiting:
                _, repos, _ = self._context((), (), state.get("session_scopes", []))
                return {"status": "waiting", "stage": "read", "error_code": "incomplete_tail", "remaining": True,
                        "verified_repos": repos}
            _, repos, _ = self._context((), (), state.get("session_scopes", []))
            return {"status": "caught_up", "session_id": state["session_id"], "remaining": False, "verified_repos": repos}
        return self._operation(session_id, "read", action)

    def acknowledge(self, session_id: str, receipt: str, outcome: str, memory_ids: list[str] | None = None) -> dict:
        def action(state: dict) -> dict:
            if not isinstance(outcome, str) or outcome not in {"saved", "duplicate", "nothing_to_save"}:
                raise CaptureError("invalid_capture_outcome")
            ids = _memory_ids([] if memory_ids is None else memory_ids)
            if outcome == "saved" and not ids:
                raise CaptureError("saved_requires_memory_ids")
            if outcome == "nothing_to_save" and ids:
                raise CaptureError("noop_cannot_include_memory_ids")
            pending = state.get("pending")
            if pending is None:
                previous = state.get("last_ack", {})
                if previous.get("receipt") == receipt and previous.get("outcome") == outcome and previous.get("memory_ids") == ids:
                    return {"status": "already_acknowledged", "receipt": receipt, "memory_ids": ids}
                raise CaptureError("unknown_receipt")
            if not isinstance(pending, dict) or pending.get("receipt") != receipt:
                raise CaptureError("unknown_receipt")
            source = self._source_for_receipt(state, pending)
            self._render(state, pending, source)
            _cursor(pending["next_cursor"])
            state["files"][pending["source"]] = {
                "cursor": pending["next_cursor"], "identity": pending["identity"],
                "fence": {"start": pending["scan_start"], "end": pending["scan_end"], "hash": pending["source_hash"]},
            }
            state["session_scopes"] = pending["next_scopes"]
            state["last_ack"] = {"receipt": receipt, "outcome": outcome, "memory_ids": ids}
            sources = self._sources(self._parent(state["session_id"], state["parent_path"]))
            index = sources.index(source)
            state["next_source"] = str(sources[(index + 1) % len(sources)].relative_to(self.transcripts_root))
            del state["pending"]
            return {"status": outcome, "receipt": receipt, "memory_ids": ids}
        return self._operation(session_id, "ack", action)

    def fail(self, session_id: str, receipt: str, stage: str, error_code: str) -> dict:
        def action(state: dict) -> dict:
            if not all(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value) for value in (stage, error_code)):
                raise CaptureError("invalid_failure_diagnostic")
            if (state.get("pending") or {}).get("receipt") != receipt:
                raise CaptureError("unknown_receipt")
            return {"status": "error", "stage": stage, "error_code": error_code, "receipt": receipt}
        return self._operation(session_id, "fail", action)

    def status(self, session_id: str) -> dict:
        def action(state: dict) -> dict:
            return {"status": "capture_status", "last_run": state.get("last_run"),
                    "last_ack": state.get("last_ack"), "pending": state.get("pending") is not None,
                    "current_capture": state.get("current_capture"),
                    "processed_sources": len(state["files"])}
        return self._operation(session_id, "status", action, record=False)

    def record_current(self, session_id: str, memory_ids: list[str]) -> dict:
        def action(state: dict) -> dict:
            ids = _memory_ids(memory_ids)
            if not ids:
                raise CaptureError("saved_requires_memory_ids")
            state["current_capture"] = {"memory_ids": ids, "evidence_kind": "hook_last_assistant_message"}
            return {"status": "current_saved", "memory_ids": ids}
        return self._operation(session_id, "record_current", action)
