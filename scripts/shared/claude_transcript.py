from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import dataclass
from typing import BinaryIO, Callable, Literal


class TranscriptError(ValueError):
    """A transcript cannot be consumed without losing its coverage boundary."""


class InvalidCursorError(TranscriptError):
    pass


class TranscriptSchemaError(TranscriptError):
    pass


class SnapshotChangedError(TranscriptError):
    pass


class OversizedRecordError(TranscriptError):
    pass


class OutputBudgetError(TranscriptError):
    pass


class TextTransformError(TranscriptError):
    pass


def _identity(text: str) -> str:
    return text


def _transform_text(text: str, transform: Callable[[str], str]) -> str:
    try:
        transformed = transform(text)
    except Exception as exc:
        raise TextTransformError("text_transform failed before transcript content could be emitted") from exc
    if not isinstance(transformed, str) or len(transformed) != len(text):
        raise TextTransformError("text_transform must return text with unchanged character count")
    return transformed


def _nonnegative_integer(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise InvalidCursorError(f"{name} must be a nonnegative integer")


@dataclass(frozen=True)
class Cursor:
    offset: int = 0
    block_index: int = 0
    char_offset: int = 0

    def __post_init__(self) -> None:
        for name in ("offset", "block_index", "char_offset"):
            _nonnegative_integer(getattr(self, name), name)


@dataclass(frozen=True)
class Fragment:
    role: str
    text: str
    message_id: str
    record_offset: int
    block_index: int
    start_char: int
    end_char: int
    cwd: str | None = None


def fragment_to_dict(fragment: Fragment) -> dict:
    return {
        "role": fragment.role,
        "text": fragment.text,
        "message_id": fragment.message_id,
        "record_offset": fragment.record_offset,
        "block_index": fragment.block_index,
        "start_char": fragment.start_char,
        "end_char": fragment.end_char,
        "cwd": fragment.cwd,
    }


def serialize_fragments(fragments: tuple[Fragment, ...] | list[Fragment]) -> str:
    return json.dumps(
        [fragment_to_dict(fragment) for fragment in fragments],
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def serialized_size(fragments: tuple[Fragment, ...] | list[Fragment]) -> int:
    return len(serialize_fragments(fragments))


@dataclass(frozen=True)
class Page:
    fragments: tuple[Fragment, ...]
    next_cursor: Cursor
    snapshot_complete: bool
    scan_bytes: int
    skipped_records: int
    skipped_blocks: int
    scan_end: int
    source_hash: str
    pending_tail: bool = False
    repo_paths: tuple[str, ...] = ()


def _absolute_repo_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    if len(json.dumps(value, ensure_ascii=True).encode("ascii")) > 1024:
        return None
    return value


def _shell_repo_paths(command: object) -> list[str]:
    if not isinstance(command, str) or any(character in command for character in ("$", "`", "\0")):
        return []
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and all(character in ";&|()\n" for character in token):
            segments.append([])
        else:
            segments[-1].append(token)
    paths = []
    for segment in segments:
        if not segment:
            continue
        arguments = segment[1:]
        candidates = []
        if segment[0] == "cd":
            while arguments and arguments[0] in {"--", "-P", "-L"}:
                arguments = arguments[1:]
            candidates = arguments[:1]
        elif segment[0].rsplit("/", 1)[-1] == "git":
            while len(arguments) > 1 and arguments[0] == "-C":
                candidates.append(arguments[1])
                arguments = arguments[2:]
        for candidate in candidates:
            if any(character in candidate for character in "*?[]"):
                continue
            path = _absolute_repo_path(candidate)
            if path is not None:
                paths.append(path)
    return paths


def _record_repo_paths(record: dict, include_sidechain: bool) -> tuple[str, ...]:
    if record.get("type") not in ("user", "assistant"):
        return ()
    if record.get("isMeta") or record.get("isCompactSummary"):
        return ()
    if record.get("isSidechain") and not include_sidechain:
        return ()
    paths = []
    cwd = _absolute_repo_path(record.get("cwd"))
    if cwd is not None:
        paths.append(cwd)
    message = record.get("message", {})
    content = message.get("content") if isinstance(message, dict) else None
    if record.get("type") == "assistant" and isinstance(content, list):
        for block in content:
            if (not isinstance(block, dict) or block.get("type") != "tool_use"
                    or not isinstance(block.get("name"), str)):
                continue
            tool_input = block.get("input")
            if not isinstance(tool_input, dict):
                continue
            for name in ("file_path", "path", "cwd"):
                path = _absolute_repo_path(tool_input.get(name))
                if path is not None:
                    paths.append(path)
            if block.get("name") == "Bash":
                paths.extend(_shell_repo_paths(tool_input.get("command")))
    return tuple(paths)


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise TranscriptSchemaError(f"{name} must be a nonempty string of at most 256 characters")
    return value


def _boolean(record: dict, name: str) -> bool:
    value = record.get(name, False)
    if type(value) is not bool:
        raise TranscriptSchemaError(f"{name} must be a boolean when present")
    return value


def _message_blocks(record: dict, include_sidechain: bool) -> tuple[str, str, list[str | None]] | None:
    row_type = record.get("type")
    if row_type not in ("user", "assistant"):
        return None
    if _boolean(record, "isMeta") or _boolean(record, "isCompactSummary"):
        return None
    if _boolean(record, "isSidechain") and not include_sidechain:
        return None
    if row_type == "user":
        origin = record.get("origin")
        if (
            isinstance(origin, dict) and origin.get("kind") == "task-notification"
            or record.get("turnOrigin") == "task_notification"
            or record.get("sourceToolAssistantUUID") is not None
            or record.get("toolUseResult") is not None
        ):
            return None
    message = record.get("message")
    if not isinstance(message, dict) or message.get("role") != row_type:
        raise TranscriptSchemaError("user and assistant records require a matching message.role")
    message_id = _identifier(record.get("uuid"), "message uuid")
    content = message.get("content")
    if isinstance(content, str):
        return row_type, message_id, [content]
    if not isinstance(content, list):
        raise TranscriptSchemaError("message.content must be text or a list of content blocks")
    blocks: list[str | None] = []
    for block in content:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str):
            raise TranscriptSchemaError("message content blocks require a string type")
        if block["type"] == "text":
            if not isinstance(block.get("text"), str):
                raise TranscriptSchemaError("text content blocks require string text")
            blocks.append(block["text"])
        else:
            blocks.append(None)
    return row_type, message_id, blocks


def _workflow_blocks(record: dict, workflow_agent_ids: frozenset[str]) -> tuple[str, str, list[str]] | None:
    if record.get("type") != "result":
        return None
    agent_id = _identifier(record.get("agentId"), "workflow agentId")
    if agent_id not in workflow_agent_ids:
        raise TranscriptSchemaError("workflow result agentId is not an authenticated session member")
    key = _identifier(record.get("key"), "workflow result key")
    if not isinstance(record.get("result"), dict):
        raise TranscriptSchemaError("workflow result must be an object")
    text = json.dumps(record["result"], ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    return "assistant", f"workflow:{agent_id}:{key}", [text]


def _reject_constant(value: str) -> None:
    raise TranscriptSchemaError(f"nonstandard JSON constant {value} is not supported")


def _decode_record(raw: bytes) -> dict:
    try:
        record = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise TranscriptSchemaError("transcript contains an invalid JSONL record") from exc
    if not isinstance(record, dict):
        raise TranscriptSchemaError("transcript JSONL records must be objects")
    return record


def _fit_fragment(
    fragments: list[Fragment],
    *,
    role: str,
    text: str,
    message_id: str,
    record_offset: int,
    block_index: int,
    start_char: int,
    budget: int,
    cwd: str | None,
) -> Fragment | None:
    def fragment(end_char: int) -> Fragment:
        return Fragment(role, text[start_char:end_char], message_id, record_offset, block_index, start_char, end_char, cwd)

    low, high = start_char + 1, min(len(text), start_char + budget)
    best: Fragment | None = None
    while low <= high:
        middle = (low + high) // 2
        candidate = fragment(middle)
        if serialized_size([*fragments, candidate]) <= budget:
            best, low = candidate, middle + 1
        else:
            high = middle - 1
    return best


def read_page(
    stream: BinaryIO,
    *,
    session_id: str,
    snapshot_end: int,
    cursor: Cursor,
    output_budget: int,
    max_record_bytes: int = 8 * 1024 * 1024,
    max_scan_bytes: int = 16 * 1024 * 1024,
    source_kind: Literal["transcript", "workflow_journal"] = "transcript",
    include_sidechain: bool = False,
    workflow_agent_ids: frozenset[str] = frozenset(),
    text_transform: Callable[[str], str] = _identity,
) -> Page:
    _identifier(session_id, "session_id")
    for name, value in (("snapshot_end", snapshot_end), ("output_budget", output_budget),
                        ("max_record_bytes", max_record_bytes), ("max_scan_bytes", max_scan_bytes)):
        _nonnegative_integer(value, name)
    if output_budget < 2:
        raise OutputBudgetError("output_budget must fit at least an empty JSON array")
    if max_record_bytes < 1 or max_scan_bytes <= max_record_bytes:
        raise InvalidCursorError("max_scan_bytes must exceed the positive max_record_bytes")
    if source_kind not in ("transcript", "workflow_journal"):
        raise TranscriptSchemaError("source_kind must be transcript or workflow_journal")
    if type(include_sidechain) is not bool:
        raise TranscriptSchemaError("include_sidechain must be a boolean")
    if not callable(text_transform):
        raise TextTransformError("text_transform must be callable")
    if not isinstance(cursor, Cursor):
        raise InvalidCursorError("cursor must be a Cursor instance")
    if cursor.offset > snapshot_end:
        raise InvalidCursorError("cursor offset exceeds the frozen snapshot boundary")
    if cursor.offset == snapshot_end and (cursor.block_index or cursor.char_offset):
        raise InvalidCursorError("a cursor at the snapshot end cannot address a content block")
    if cursor.offset:
        stream.seek(cursor.offset - 1)
        if stream.read(1) != b"\n":
            raise InvalidCursorError("cursor offset must start at a JSONL record boundary")

    initial_offset = cursor.offset
    current = cursor
    scan_end = initial_offset
    fragments: list[Fragment] = []
    skipped_records = skipped_blocks = 0
    source_hash = hashlib.sha256()
    repo_paths: list[str] = []

    def add_repo_paths(paths: tuple[str, ...]) -> None:
        for path in paths:
            if path not in repo_paths and len(repo_paths) < 8:
                repo_paths.append(path)

    def page(*, pending_tail: bool = False) -> Page:
        return Page(tuple(fragments), current, current.offset == snapshot_end,
                    scan_end - initial_offset, skipped_records, skipped_blocks,
                    scan_end, source_hash.hexdigest(), pending_tail, tuple(repo_paths))

    while current.offset < snapshot_end:
        remaining_scan = max_scan_bytes - (scan_end - initial_offset)
        if remaining_scan <= 0:
            return page()
        stream.seek(current.offset)
        limit = min(max_record_bytes + 1, snapshot_end - current.offset, remaining_scan)
        raw = stream.readline(limit)
        scan_end = current.offset + len(raw)
        source_hash.update(raw)
        if not raw:
            raise SnapshotChangedError("transcript ended before its frozen snapshot boundary")
        if len(raw) > max_record_bytes:
            raise OversizedRecordError(f"JSONL record exceeds max_record_bytes={max_record_bytes}")
        if not raw.endswith(b"\n"):
            if scan_end == snapshot_end:
                return page(pending_tail=True)
            if len(raw) < limit:
                raise SnapshotChangedError("transcript ended before its frozen snapshot boundary")
            return page()
        record_end = scan_end
        if not raw.strip():
            if current.block_index or current.char_offset:
                raise InvalidCursorError("cursor addresses a block inside a blank JSONL record")
            skipped_records += 1
            current = Cursor(record_end)
            continue
        record = _decode_record(raw)
        if "sessionId" in record and record["sessionId"] != session_id:
            raise TranscriptSchemaError("record sessionId does not match the authenticated session")
        if source_kind == "transcript" and record.get("type") in ("user", "assistant"):
            if record.get("sessionId") != session_id:
                raise TranscriptSchemaError("message record requires the authenticated sessionId")
        normalized = (
            _workflow_blocks(record, workflow_agent_ids)
            if source_kind == "workflow_journal" else _message_blocks(record, include_sidechain)
        )
        record_paths = _record_repo_paths(record, include_sidechain) if source_kind == "transcript" else ()
        if normalized is None:
            if current.block_index or current.char_offset:
                raise InvalidCursorError("cursor addresses a block inside an excluded record")
            add_repo_paths(record_paths)
            skipped_records += 1
            current = Cursor(record_end)
            continue
        role, message_id, blocks = normalized
        cwd = record.get("cwd") if source_kind == "transcript" else None
        if cwd is not None and (not isinstance(cwd, str) or len(cwd) > 4096):
            raise TranscriptSchemaError("message cwd must be text of at most 4096 characters when present")
        if current.block_index > len(blocks) or current.block_index == len(blocks) and current.char_offset:
            raise InvalidCursorError("cursor content block index exceeds the message content")
        emitted = False
        for index in range(current.block_index, len(blocks)):
            text = blocks[index]
            start_char = current.char_offset if index == current.block_index else 0
            if text is None:
                if start_char:
                    raise InvalidCursorError("cursor addresses text inside an excluded content block")
                skipped_blocks += 1
                continue
            text = _transform_text(text, text_transform)
            if start_char > len(text):
                raise InvalidCursorError("cursor character offset exceeds the text block")
            if start_char == len(text):
                continue
            current = Cursor(current.offset, index, start_char)
            candidate = _fit_fragment(
                fragments, role=role, text=text, message_id=message_id,
                record_offset=current.offset, block_index=index, start_char=start_char, budget=output_budget,
                cwd=cwd,
            )
            if candidate is None:
                if not fragments:
                    raise OutputBudgetError("output_budget cannot fit the next text character and its source metadata")
                return page()
            fragments.append(candidate)
            add_repo_paths(record_paths)
            emitted = True
            if candidate.end_char < len(text):
                current = Cursor(current.offset, index, candidate.end_char)
                return page()
        if not emitted:
            skipped_records += 1
        add_repo_paths(record_paths)
        current = Cursor(record_end)
    return page()
