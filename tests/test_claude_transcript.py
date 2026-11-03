from __future__ import annotations

import hashlib
import io
import json

import pytest

from scripts.shared.claude_transcript import (
    Cursor,
    Fragment,
    InvalidCursorError,
    OutputBudgetError,
    OversizedRecordError,
    SnapshotChangedError,
    TextTransformError,
    TranscriptSchemaError,
    fragment_to_dict,
    read_page,
    serialize_fragments,
    serialized_size,
)

SESSION = "synthetic-session"


def message(role: str, content: str | list, **extra) -> dict:
    return {
        "type": role,
        "sessionId": SESSION,
        "uuid": f"{role}-message",
        "message": {"role": role, "content": content},
        **extra,
    }


def encode(*records: dict) -> bytes:
    return b"".join((json.dumps(record, ensure_ascii=False) + "\n").encode() for record in records)


def page(data: bytes, **options):
    return read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                     cursor=Cursor(), output_budget=8192, **options)


def collect(data: bytes, *, budget: int = 600, **options):
    pages = []
    cursor = Cursor()
    for _ in range(2000):
        result = read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                           cursor=cursor, output_budget=budget, **options)
        pages.append(result)
        assert result.next_cursor != cursor or result.snapshot_complete
        assert serialized_size(result.fragments) <= budget
        assert result.source_hash == hashlib.sha256(data[cursor.offset:result.scan_end]).hexdigest()
        if result.snapshot_complete:
            return pages
        cursor = result.next_cursor
    raise AssertionError("bounded transcript pagination did not complete")


def test_extracts_only_message_text_and_preserves_cwd():
    records = [
        {"type": "file-history-snapshot", "snapshot": {"hidden": "FILE_SECRET"}},
        message("user", "A real question", cwd="/workspace/first"),
        message("assistant", [
            {"type": "thinking", "thinking": "THINKING_SECRET"},
            {"type": "text", "text": "A confirmed finding"},
            {"type": "tool_use", "name": "Read", "input": {"secret": "INPUT_SECRET"}},
        ], cwd="/workspace/second"),
        message("user", [{"type": "tool_result", "tool_use_id": "tool", "content": "RESULT_SECRET"}]),
        message("user", "FEEDBACK_SECRET", isMeta=True),
        message("user", "COMPACTION_SECRET", isCompactSummary=True),
        message("user", "NOTIFICATION_SECRET", origin={"kind": "task-notification"}),
        message("user", "NOTIFICATION_SECRET", turnOrigin="task_notification"),
        message("user", "RESULT_SECRET", sourceToolAssistantUUID="assistant-id"),
        message("user", "RESULT_SECRET", toolUseResult="hidden"),
        {"type": "system", "subtype": "stop_hook_summary", "hookErrors": ["HOOK_SECRET"]},
    ]
    result = page(encode(*records))
    assert [fragment.text for fragment in result.fragments] == ["A real question", "A confirmed finding"]
    assert [fragment.cwd for fragment in result.fragments] == ["/workspace/first", "/workspace/second"]
    assert result.fragments[1].block_index == 1
    assert "SECRET" not in serialize_fragments(result.fragments)
    assert result.snapshot_complete
    assert result.skipped_records == 9
    assert result.skipped_blocks == 3


def test_child_messages_require_authenticated_sidechain_opt_in():
    data = encode(message("assistant", "child result", isSidechain=True, agentId="child"))
    assert not page(data).fragments
    assert page(data, include_sidechain=True).fragments[0].text == "child result"


def test_tool_only_pages_return_bounded_paths_without_tool_payloads():
    record = message("assistant", [
        {"type": "tool_use", "name": "Read", "input": {
            "file_path": "/work/repo/module.py", "query": "PRIVATE_QUERY", "content": "PRIVATE_CONTENT",
        }},
        {"type": "tool_use", "name": "Glob", "input": {"path": "/work/another", "pattern": "PRIVATE_PATTERN"}},
        {"type": "tool_use", "name": "Bash", "input": {"cwd": "/work/third", "command": "echo PRIVATE_COMMAND"}},
    ], cwd="/work/nongit-parent")
    data = encode(record)
    result = page(data)
    assert result.repo_paths == ("/work/nongit-parent", "/work/repo/module.py", "/work/another", "/work/third")
    assert result.fragments == ()
    assert result.next_cursor == Cursor(len(data))
    assert result.snapshot_complete
    assert "PRIVATE_" not in json.dumps(result.repo_paths)
    assert result.source_hash == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(("command", "expected"), [
    ("cd /work/repo && pytest", ("/work/repo",)),
    ("cd -- '/work/repo with spaces'\npytest", ("/work/repo with spaces",)),
    ('git -C "/work/repo with spaces" status', ("/work/repo with spaces",)),
    ("echo text; /usr/bin/git -C /work/first -C /work/second log", ("/work/first", "/work/second")),
    ("echo 'cd /work/not-an-operation'", ()),
    ("echo git -C /work/not-an-operation", ()),
    ("git log --grep '-C' /work/not-an-option", ()),
    ("cd relative/path", ()),
    ("cd /work/*", ()),
    ("cd /work/$EXPANDED", ()),
    ("cd /work/`command`", ()),
    ("cd '/unterminated", ()),
])
def test_literal_shell_directory_hints_are_parsed_without_evaluation(command, expected):
    record = message("assistant", [{"type": "tool_use", "name": "Bash", "input": {"command": command}}])
    result = page(encode(record))
    assert result.repo_paths == expected
    assert result.fragments == ()


def test_shell_path_hint_extraction_never_executes_commands(tmp_path):
    marker = tmp_path / "must-not-exist"
    records = [message("assistant", [{"type": "tool_use", "name": "Bash", "input": {
        "command": f"cd /work/repo && touch '{marker}'",
    }}]), message("assistant", [{"type": "tool_use", "name": "Bash", "input": {
        "command": f"cd $(touch '{marker}')",
    }}])]
    result = page(encode(*records))
    assert result.repo_paths == ("/work/repo",)
    assert not marker.exists()


def test_path_hints_ignore_prose_results_thinking_and_unapproved_fields():
    data = encode(
        message("assistant", "The untrusted prose mentions /work/prose"),
        message("assistant", [
            {"type": "thinking", "thinking": "hidden", "path": "/work/thinking"},
            {"type": "tool_use", "name": "Search", "input": {"query": "/work/query", "content": "/work/content"}},
        ]),
        message("user", [{"type": "tool_result", "tool_use_id": "tool", "content": "/work/result"}]),
        message("assistant", "hidden", cwd="/work/excluded", isMeta=True),
        message("assistant", "hidden", cwd="/work/child", isSidechain=True),
    )
    assert page(data).repo_paths == ()


def test_paths_are_deduplicated_limited_and_capped_by_ascii_encoded_size():
    paths = ["relative", "/bad\npath", "/bad\0path", "/" + "x" * 1024, "/" + "🙂" * 100]
    paths += ["/work/first", "/work/first", *[f"/work/repo-{index}" for index in range(12)]]
    blocks = [{"type": "tool_use", "name": "Read", "input": {"file_path": value}} for value in paths]
    result = page(encode(message("assistant", blocks)))
    assert result.repo_paths == ("/work/first", *[f"/work/repo-{index}" for index in range(7)])
    assert len(result.repo_paths) == 8
    assert all(len(json.dumps(value, ensure_ascii=True).encode("ascii")) <= 1024 for value in result.repo_paths)


def test_paths_from_read_but_unconsumed_records_are_deferred_until_visible():
    first = message("assistant", "first")
    second = message("assistant", [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/work/not-yet-consumed"}},
        {"type": "text", "text": "following visible text"},
    ])
    data = encode(first, second)
    budget = serialized_size([Fragment("assistant", "first", "assistant-message", 0, 0, 0, 5)])
    result = read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                       cursor=Cursor(), output_budget=budget)
    assert result.fragments[0].text == "first"
    assert result.next_cursor.offset == len(encode(first))
    assert result.repo_paths == ()
    following = read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                          cursor=result.next_cursor, output_budget=8192)
    assert following.repo_paths == ("/work/not-yet-consumed",)
    assert following.fragments[0].text == "following visible text"


def test_partial_text_pages_include_their_own_authenticated_row_hints():
    data = encode(message("assistant", [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/work/consumed-record"}},
        {"type": "text", "text": "large finding " * 100},
    ]))
    pages = collect(data, budget=400)
    assert len(pages) > 1
    assert all(result.repo_paths == ("/work/consumed-record",) for result in pages)


def test_large_single_jsonl_record_resumes_without_losing_unicode_or_escaping():
    text = ('A"\\\n🙂é' * 6000) + "last-character"
    data = encode(message("assistant", text))
    pages = collect(data, budget=900)
    fragments = [fragment for result in pages for fragment in result.fragments]
    assert len(pages) > 100
    assert "".join(fragment.text for fragment in fragments) == text
    assert all(fragment.record_offset == 0 for fragment in fragments)
    assert fragments[0].start_char == 0
    assert fragments[-1].end_char == len(text)
    assert all(left.end_char == right.start_char for left, right in zip(fragments, fragments[1:]))
    assert all(result.next_cursor.offset == 0 for result in pages[:-1])
    assert pages[-1].next_cursor == Cursor(len(data))
    assert pages[0].scan_end == len(data)
    assert all(serialize_fragments(result.fragments).isascii() for result in pages)


def test_pagination_retains_original_block_indices_and_record_offsets():
    first = message("assistant", [
        {"type": "thinking", "thinking": "excluded"},
        {"type": "text", "text": "first " * 100},
        {"type": "tool_use", "name": "Read", "input": {}},
        {"type": "text", "text": "second " * 100},
    ])
    second = message("user", "final question")
    data = encode(first, second)
    pages = collect(data, budget=500)
    fragments = [fragment for result in pages for fragment in result.fragments]
    by_source: dict[tuple[int, int], list[str]] = {}
    for fragment in fragments:
        by_source.setdefault((fragment.record_offset, fragment.block_index), []).append(fragment.text)
    assert {key: "".join(parts) for key, parts in by_source.items()} == {
        (0, 1): "first " * 100,
        (0, 3): "second " * 100,
        (len(encode(first)), 0): "final question",
    }


def test_transform_masks_complete_secrets_before_they_cross_page_boundaries():
    secret = "tok_" + "X" * 40
    prefix = "prefix " * 30
    original = prefix + secret + " after " * 40
    data = encode(message("assistant", original))
    split_at = len(prefix) + 10
    budget = serialized_size([Fragment("assistant", original[:split_at], "assistant-message", 0, 0, 0, split_at)])
    unmasked = read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                         cursor=Cursor(), output_budget=budget)
    assert len(prefix) < unmasked.fragments[0].end_char < len(prefix) + len(secret)
    transformed_inputs = []

    def mask_whole_block(text):
        transformed_inputs.append(text)
        return text.replace(secret, "*" * len(secret))

    pages = collect(data, budget=budget, text_transform=mask_whole_block)
    fragments = [fragment for result in pages for fragment in result.fragments]
    assert all(text == original for text in transformed_inputs)
    assert "".join(fragment.text for fragment in fragments) == original.replace(secret, "*" * len(secret))
    assert all("tok_" not in fragment.text and "X" not in fragment.text for fragment in fragments)
    assert fragments[0].start_char == 0
    assert fragments[-1].end_char == len(original)
    assert all(left.end_char == right.start_char for left, right in zip(fragments, fragments[1:]))
    assert all(result.source_hash == hashlib.sha256(data).hexdigest() for result in pages)


def test_workflow_result_transform_receives_complete_normalized_result():
    data = encode({"type": "result", "agentId": "verified", "key": "analysis",
                   "result": {"token": "sensitive-value" * 50}})
    complete_text = json.dumps({"token": "sensitive-value" * 50}, ensure_ascii=True, separators=(",", ":"))
    received = []

    def mask_whole_result(text):
        received.append(text)
        return text.replace("sensitive-value", "*" * len("sensitive-value"))

    pages = collect(data, budget=400, source_kind="workflow_journal",
                    workflow_agent_ids=frozenset({"verified"}), text_transform=mask_whole_result)
    assert len(pages) > 1
    assert all(text == complete_text for text in received)
    output = "".join(fragment.text for result in pages for fragment in result.fragments)
    assert json.loads(output) == {"token": "*" * (len("sensitive-value") * 50)}


@pytest.mark.parametrize("transform", [lambda text: text[:-1], lambda text: text + "!", lambda text: None, None])
def test_transform_contract_rejects_length_changes_or_nontext_before_emitting(transform):
    with pytest.raises(TextTransformError):
        page(encode(message("assistant", "finding")), text_transform=transform)


def test_transform_failures_have_a_typed_error_without_echoing_source_text():
    def fail(text):
        raise RuntimeError("sensitive source contents")

    with pytest.raises(TextTransformError, match="failed before transcript content") as raised:
        page(encode(message("assistant", "finding")), text_transform=fail)
    assert "sensitive" not in str(raised.value)


def test_budget_accounts_for_ascii_escaping_and_source_metadata_exactly():
    fragment = Fragment("assistant", "🙂", "assistant-message", 0, 0, 0, 1)
    budget = serialized_size([fragment])
    data = encode(message("assistant", "🙂🙂"))
    result = read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                       cursor=Cursor(), output_budget=budget)
    assert result.fragments == (fragment,)
    assert result.next_cursor == Cursor(0, 0, 1)
    assert serialized_size(result.fragments) == budget
    assert json.loads(serialize_fragments(result.fragments)) == [fragment_to_dict(fragment)]


def test_snapshot_boundary_excludes_concurrent_appends():
    original = encode(message("assistant", "frozen finding"))
    appended = encode(message("assistant", "future finding"))
    result = read_page(io.BytesIO(original + appended), session_id=SESSION,
                       snapshot_end=len(original), cursor=Cursor(), output_budget=8192)
    assert [fragment.text for fragment in result.fragments] == ["frozen finding"]
    assert result.scan_end == len(original)
    assert result.scan_bytes == len(original)
    assert result.source_hash == hashlib.sha256(original).hexdigest()
    assert result.snapshot_complete


def test_source_hash_uses_the_same_bytes_that_produced_fragments():
    original = encode(message("assistant", "before"))
    changed = original.replace(b"before", b"after!")

    class ChangingStream(io.BytesIO):
        def readline(self, size=-1):
            raw = super().readline(size)
            position = self.tell()
            self.seek(0)
            self.write(changed)
            self.seek(position)
            return raw

    stream = ChangingStream(original)
    result = read_page(stream, session_id=SESSION, snapshot_end=len(original),
                       cursor=Cursor(), output_budget=8192)
    assert result.fragments[0].text == "before"
    assert stream.getvalue() == changed
    assert result.source_hash == hashlib.sha256(original).hexdigest()
    assert result.source_hash != hashlib.sha256(changed).hexdigest()


@pytest.mark.parametrize("tail", [b'{"type":', b'{"unfinished":true}'])
def test_partial_trailing_record_remains_pending_without_consumption(tail):
    complete = encode(message("assistant", "complete finding"))
    data = complete + tail
    result = page(data)
    assert [fragment.text for fragment in result.fragments] == ["complete finding"]
    assert result.next_cursor == Cursor(len(complete))
    assert result.pending_tail
    assert not result.snapshot_complete
    assert result.scan_end == len(data)
    assert result.source_hash == hashlib.sha256(data).hexdigest()


def test_partial_snapshot_does_not_read_newline_appended_beyond_boundary():
    data = encode(message("assistant", "finding"))
    result = read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data) - 1,
                       cursor=Cursor(), output_budget=8192)
    assert not result.fragments
    assert result.next_cursor == Cursor()
    assert result.pending_tail


@pytest.mark.parametrize("cut", [0, 1, 50])
def test_truncation_before_snapshot_boundary_fails(cut):
    data = encode(message("assistant", "a durable finding"))
    with pytest.raises(SnapshotChangedError, match="frozen snapshot boundary"):
        read_page(io.BytesIO(data[:cut]), session_id=SESSION, snapshot_end=len(data),
                  cursor=Cursor(), output_budget=8192)


def test_record_size_limit_fails_without_skipping_the_record():
    data = encode(message("assistant", "x" * 1000))
    with pytest.raises(OversizedRecordError, match="max_record_bytes=300"):
        page(data, max_record_bytes=300, max_scan_bytes=1000)


def test_scan_limit_yields_a_resumable_record_boundary_without_losing_ranges():
    records = [{"type": "metadata", "padding": "x" * 100} for _ in range(20)]
    data = encode(*records, message("assistant", "last finding"))
    cursor = Cursor()
    skipped = 0
    for _ in range(20):
        result = read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                           cursor=cursor, output_budget=8192, max_record_bytes=300, max_scan_bytes=700)
        assert result.scan_bytes <= 700
        assert result.scan_bytes == result.scan_end - cursor.offset
        assert result.source_hash == hashlib.sha256(data[cursor.offset:result.scan_end]).hexdigest()
        skipped += result.skipped_records
        if result.snapshot_complete:
            assert result.fragments[0].text == "last finding"
            break
        assert result.next_cursor.offset > cursor.offset
        cursor = result.next_cursor
    else:
        raise AssertionError("scan-limited reader did not complete")
    assert skipped == 20


def test_workflow_results_use_the_same_bounded_cursor_and_ascii_budget():
    result_object = {"facts": [{"claim": "confirmed é🙂 " * 100}], "count": 1}
    data = encode(
        {"type": "launched"},
        {"type": "started", "agentId": "verified-child", "key": "analysis", "label": "hidden", "phase": "check"},
        {"type": "result", "agentId": "verified-child", "key": "analysis", "result": result_object},
    )
    pages = collect(data, budget=600, source_kind="workflow_journal",
                    workflow_agent_ids=frozenset({"verified-child"}))
    fragments = [fragment for result in pages for fragment in result.fragments]
    assert len(pages) > 1
    assert json.loads("".join(fragment.text for fragment in fragments)) == result_object
    assert all(fragment.role == "assistant" for fragment in fragments)
    assert all(fragment.message_id == "workflow:verified-child:analysis" for fragment in fragments)
    assert all(fragment.cwd is None for fragment in fragments)
    assert sum(result.skipped_records for result in pages) == 2


@pytest.mark.parametrize("record", [
    {"type": "result", "agentId": "unverified", "key": "analysis", "result": {}},
    {"type": "result", "agentId": "verified", "key": "analysis", "result": "not an object"},
    {"type": "result", "agentId": "verified", "result": {}},
])
def test_workflow_journal_rejects_unverified_or_malformed_results(record):
    with pytest.raises(TranscriptSchemaError):
        page(encode(record), source_kind="workflow_journal", workflow_agent_ids=frozenset({"verified"}))


@pytest.mark.parametrize("record", [
    message("assistant", "wrong session", sessionId="another-session"),
    {key: value for key, value in message("assistant", "missing session").items() if key != "sessionId"},
    message("assistant", "wrong role", message={"role": "user", "content": "hidden"}),
    message("assistant", [{"type": "text", "text": 12}]),
    message("assistant", ["not a content block"]),
    message("assistant", "bad flag", isMeta="false"),
    message("assistant", "bad cwd", cwd=123),
    message("assistant", "large cwd", cwd="/" * 4097),
    message("assistant", "bad uuid", uuid="x" * 257),
    {"type": "metadata", "sessionId": "different-session"},
])
def test_record_contract_rejects_schema_and_session_drift(record):
    with pytest.raises(TranscriptSchemaError):
        page(encode(record))


@pytest.mark.parametrize("data", [b"not-json\n", b"[]\n", b'{"value":NaN}\n', b'{"value":"\xff"}\n'])
def test_invalid_jsonl_never_advances_a_cursor(data):
    with pytest.raises(TranscriptSchemaError):
        page(data)


@pytest.mark.parametrize("cursor", [Cursor(1), Cursor(0, 2, 0), Cursor(0, 0, 1000)])
def test_invalid_resume_cursor_is_rejected(cursor):
    data = encode(message("assistant", "short"))
    with pytest.raises(InvalidCursorError):
        read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                  cursor=cursor, output_budget=8192)


@pytest.mark.parametrize("arguments", [(-1, 0, 0), (True, 0, 0), (0, -1, 0), (0, 0, 1.0)])
def test_cursor_coordinates_require_nonnegative_integers(arguments):
    with pytest.raises(InvalidCursorError):
        Cursor(*arguments)


def test_cursor_inside_excluded_content_is_rejected():
    data = encode(message("assistant", [{"type": "thinking", "thinking": "excluded"}]))
    with pytest.raises(InvalidCursorError, match="excluded content block"):
        read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                  cursor=Cursor(0, 0, 1), output_budget=8192)


def test_empty_snapshot_and_blank_records_are_explicitly_consumed():
    empty = page(b"")
    assert empty.snapshot_complete
    assert empty.source_hash == hashlib.sha256(b"").hexdigest()
    result = page(b"\n  \r\n")
    assert result.snapshot_complete
    assert result.next_cursor == Cursor(5)
    assert result.skipped_records == 2
    assert not result.fragments


def test_budget_that_cannot_fit_source_metadata_fails_explicitly():
    data = encode(message("assistant", "finding"))
    with pytest.raises(OutputBudgetError, match="source metadata"):
        read_page(io.BytesIO(data), session_id=SESSION, snapshot_end=len(data),
                  cursor=Cursor(), output_budget=2)
