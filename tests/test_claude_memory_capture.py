from __future__ import annotations

import json
import subprocess
import uuid

import pytest

from scripts.shared.atomic_json import exclusive_file_lock
from scripts.shared.claude_memory_capture import CaptureStore, MAX_OUTPUT_BYTES, resolve_repo


def row(session_id, text="The parser validates source identities.", *, cwd=None, agent_id=None):
    value = {"type": "assistant", "sessionId": session_id, "uuid": str(uuid.uuid4()),
             "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    if cwd is not None:
        value["cwd"] = str(cwd)
    if agent_id is not None:
        value.update(agentId=agent_id, isSidechain=True)
    return value


def write_rows(path, *rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value) + "\n" for value in rows), encoding="utf-8")


@pytest.fixture
def capture(tmp_path):
    session_id = str(uuid.uuid4())
    logs = tmp_path / "logs"
    parent = logs / "project" / f"{session_id}.jsonl"
    write_rows(parent, row(session_id))
    state = tmp_path / "state"
    store = CaptureStore(logs, state, allowed_repo_roots=(tmp_path,))
    return store, session_id, parent, state


def read_state(state, session_id):
    return json.loads((state / f"{session_id}.json").read_text())


def test_context_is_pending_until_explicit_ack_and_contains_no_stored_prose(capture):
    store, session_id, parent, state = capture
    result = store.read(session_id, str(parent))
    assert result["status"] == "ready"
    assert result["untrusted_context"][0]["text"] == "The parser validates source identities."
    persisted = read_state(state, session_id)
    assert persisted["files"] == {}
    assert "The parser validates" not in json.dumps(persisted)
    assert store.read(session_id, str(parent))["receipt"] == result["receipt"]
    acknowledged = store.acknowledge(session_id, result["receipt"], "nothing_to_save")
    assert acknowledged["status"] == "nothing_to_save"
    assert store.read(session_id, str(parent))["status"] == "caught_up"
    checkpoint = next(iter(read_state(state, session_id)["files"].values()))
    assert checkpoint["cursor"]["offset"] == parent.stat().st_size


def test_saved_requires_uuid_confirmation_and_failed_save_retains_page(capture):
    store, session_id, parent, state = capture
    page = store.read(session_id, str(parent))
    assert store.acknowledge(session_id, page["receipt"], "saved")["error_code"] == "saved_requires_memory_ids"
    assert read_state(state, session_id)["files"] == {}
    failure = store.fail(session_id, page["receipt"], "save", "tool_denied")
    assert failure["status"] == "error"
    assert store.status(session_id)["last_run"] == failure
    assert store.status(session_id)["last_run"] == failure
    replay = store.read(session_id, str(parent))
    assert replay["receipt"] == page["receipt"]
    memory_id = str(uuid.uuid4())
    result = store.acknowledge(session_id, page["receipt"], "saved", [memory_id])
    assert result["memory_ids"] == [memory_id]
    assert store.acknowledge(session_id, page["receipt"], "saved", [memory_id])["status"] == "already_acknowledged"


def test_status_does_not_create_or_modify_capture_state(capture):
    store, session_id, parent, state = capture
    assert store.status(session_id)["last_run"] is None
    assert not (state / f"{session_id}.json").exists()
    store.read(session_id, str(parent))
    before = (state / f"{session_id}.json").read_bytes()
    store.status(session_id)
    assert (state / f"{session_id}.json").read_bytes() == before


def test_append_after_snapshot_is_deferred_without_invalidating_ack(capture):
    store, session_id, parent, _ = capture
    page = store.read(session_id, str(parent))
    with parent.open("a") as stream:
        stream.write(json.dumps(row(session_id, "New technical finding.")) + "\n")
    assert store.acknowledge(session_id, page["receipt"], "nothing_to_save")["status"] == "nothing_to_save"
    following = store.read(session_id, str(parent))
    assert [fragment["text"] for fragment in following["untrusted_context"]] == ["New technical finding."]


@pytest.mark.parametrize("mutation", ["rewrite", "truncate", "replace"])
def test_source_drift_prevents_acknowledgement(capture, mutation):
    store, session_id, parent, state = capture
    page = store.read(session_id, str(parent))
    if mutation == "rewrite":
        parent.write_bytes(parent.read_bytes().replace(b"parser", b"worker"))
    elif mutation == "truncate":
        parent.write_bytes(parent.read_bytes()[:-2])
    else:
        replacement = parent.with_suffix(".new")
        replacement.write_bytes(parent.read_bytes())
        replacement.replace(parent)
    assert store.acknowledge(session_id, page["receipt"], "nothing_to_save")["status"] == "error"
    assert read_state(state, session_id)["files"] == {}
    assert read_state(state, session_id)["pending"]["receipt"] == page["receipt"]


def test_large_record_is_paginated_with_bounded_output_and_exact_coverage(capture):
    store, session_id, parent, _ = capture
    text = "Confirmed technical evidence \u03bb\n" * 12000
    write_rows(parent, row(session_id, text))
    observed = []
    for _ in range(1000):
        page = store.read(session_id, str(parent))
        if page["status"] == "caught_up":
            break
        assert page["status"] == "ready", page
        assert len(json.dumps(page, ensure_ascii=True).encode("ascii")) <= MAX_OUTPUT_BYTES
        observed.extend(fragment["text"] for fragment in page["untrusted_context"])
        assert store.acknowledge(session_id, page["receipt"], "nothing_to_save")["status"] == "nothing_to_save"
    else:
        pytest.fail("bounded pages failed to converge")
    assert "".join(observed) == text


def test_parent_child_and_workflow_journal_results_are_all_read(capture):
    store, session_id, parent, _ = capture
    children = parent.with_suffix("") / "subagents"
    child = children / "agent-child.jsonl"
    workflow = children / "workflows" / "workflow-one"
    write_rows(child, row(session_id, "Child technical finding.", agent_id="child"))
    write_rows(workflow / "agent-worker.jsonl", row(session_id, "Workflow technical finding.", agent_id="worker"))
    write_rows(workflow / "journal.jsonl", {"type": "launched"},
               {"type": "started", "agentId": "worker", "key": "review"},
               {"type": "result", "agentId": "worker", "key": "review", "result": {"finding": "Journal result."}})
    observed = []
    first = store.read(session_id, str(child))
    assert first["remaining"] is True
    for page in [first]:
        observed.extend(fragment["text"] for fragment in page["untrusted_context"])
        store.acknowledge(session_id, page["receipt"], "nothing_to_save")
    for _ in range(10):
        page = store.read(session_id, str(parent))
        if page["status"] == "caught_up":
            break
        assert page["status"] == "ready", page
        observed.extend(fragment["text"] for fragment in page["untrusted_context"])
        store.acknowledge(session_id, page["receipt"], "nothing_to_save")
    assert any("Child technical" in text for text in observed)
    assert any("Workflow technical" in text for text in observed)
    assert any("Journal result" in text for text in observed)


def test_incomplete_parent_tail_does_not_starve_completed_child(capture):
    store, session_id, parent, _ = capture
    parent.write_bytes(b'{"type":"assistant"')
    child = parent.with_suffix("") / "subagents" / "agent-child.jsonl"
    write_rows(child, row(session_id, "Completed child result.", agent_id="child"))
    page = store.read(session_id, str(parent))
    assert page["status"] == "ready"
    assert page["untrusted_context"][0]["text"] == "Completed child result."
    store.acknowledge(session_id, page["receipt"], "nothing_to_save")
    assert store.read(session_id, str(parent))["status"] == "waiting"


def test_journal_cannot_reference_an_unrelated_agent(capture):
    store, session_id, parent, _ = capture
    journal = parent.with_suffix("") / "subagents" / "workflows" / "w" / "journal.jsonl"
    write_rows(journal, {"type": "result", "agentId": "unrelated", "key": "x", "result": {"finding": "Untrusted."}})
    first = store.read(session_id, str(parent))
    store.acknowledge(session_id, first["receipt"], "nothing_to_save")
    assert store.read(session_id, str(parent))["status"] == "error"


def test_source_path_escape_and_symlinks_are_rejected(capture, tmp_path):
    store, session_id, parent, _ = capture
    outside = tmp_path / f"{session_id}.jsonl"
    write_rows(outside, row(session_id))
    assert store.read(session_id, str(outside))["error_code"] == "source_outside_transcripts_root"
    alias = parent.parent / "alias.jsonl"
    alias.symlink_to(parent)
    assert store.read(session_id, str(alias))["error_code"] == "source_symlink_rejected"


def test_wrong_session_and_malformed_input_are_safe_failures(capture):
    store, session_id, parent, state = capture
    write_rows(parent, row(str(uuid.uuid4()), "PRIVATE CANARY MUST NOT LEAK"))
    result = store.read(session_id, str(parent))
    assert result["status"] == "error"
    assert "PRIVATE CANARY" not in json.dumps(result)
    assert read_state(state, session_id)["files"] == {}
    parent.write_bytes(b'{"PRIVATE CANARY": invalid}\n')
    assert "PRIVATE CANARY" not in json.dumps(store.read(session_id, str(parent)))


def test_scope_uses_verified_git_roots_and_separates_repositories(capture, tmp_path):
    store, session_id, parent, _ = capture
    one, two = tmp_path / "one", tmp_path / "two"
    for path in (one, two):
        path.mkdir()
        subprocess.run(["git", "init", "-q", str(path)], check=True)
    write_rows(parent, row(session_id, "First repository fact.", cwd=one),
               row(session_id, "Second repository fact.", cwd=two),
               row(session_id, "Unscoped preference.", cwd=parent.parent))
    page = store.read(session_id, str(parent))
    assert {scope["repo"] for scope in page["verified_repos"]} == {"one", "two"}
    mapping = {scope["id"]: scope for scope in page["verified_repos"]}
    assert [mapping[key]["repo"] for key in page["untrusted_context"][0]["verified_repo_ids"]] == ["one"]
    assert page["untrusted_context"][2]["verified_repo_ids"] == []
    assert resolve_repo(str(parent.parent), (tmp_path,)) is None


def test_secrets_are_redacted_before_context_is_returned(capture):
    store, session_id, parent, _ = capture
    write_rows(parent, row(session_id, "Technical finding.\napi_key = sk-123456789012345678901234\n123-45-6789"))
    page = store.read(session_id, str(parent))
    serialized = json.dumps(page)
    assert "sk-123456789012345678901234" not in serialized
    assert "123-45-6789" not in serialized
    assert "Technical finding" in serialized


def test_unknown_receipt_does_not_advance_any_source(capture):
    store, session_id, parent, state = capture
    store.read(session_id, str(parent))
    assert store.acknowledge(session_id, "wrong", "duplicate")["error_code"] == "unknown_receipt"
    assert read_state(state, session_id)["files"] == {}


def test_concurrent_capture_is_handled_without_touching_state(capture):
    store, session_id, parent, state = capture
    with exclusive_file_lock(state / f"{session_id}.lock"):
        assert store.read(session_id, str(parent))["status"] == "busy"
    assert not (state / f"{session_id}.json").exists()


@pytest.mark.parametrize("bad_pending", [False, 42, [], {"receipt": "broken"}])
def test_corrupt_pending_state_is_rejected_without_replacing_it(capture, bad_pending):
    store, session_id, parent, state = capture
    state.mkdir()
    path = state / f"{session_id}.json"
    value = {"version": 1, "session_id": session_id, "files": {}, "pending": bad_pending}
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    assert store.read(session_id, str(parent))["status"] == "error"
    assert path.read_bytes() == before


def test_ack_rechecks_parsed_coverage_even_if_cursor_shape_is_valid(capture):
    store, session_id, parent, state = capture
    page = store.read(session_id, str(parent))
    path = state / f"{session_id}.json"
    value = read_state(state, session_id)
    value["pending"]["next_cursor"] = {"offset": 0, "block_index": 0, "char_offset": 1}
    path.write_text(json.dumps(value))
    assert store.acknowledge(session_id, page["receipt"], "nothing_to_save")["status"] == "error"
    assert read_state(state, session_id)["files"] == {}


def test_scope_changes_between_read_and_ack_are_rejected(capture):
    store, session_id, parent, state = capture
    write_rows(parent, row(session_id, cwd=parent.parent))
    scope = {"repo": "original", "root": "/verified/original"}
    store.repo_resolver = lambda _: dict(scope)
    page = store.read(session_id, str(parent))
    scope.update(repo="changed", root="/verified/changed")
    assert store.acknowledge(session_id, page["receipt"], "nothing_to_save")["error_code"] == "context_changed_since_read"
    assert read_state(state, session_id)["files"] == {}


def test_long_verified_paths_do_not_wedge_the_output_envelope(capture):
    store, session_id, parent, _ = capture
    write_rows(parent, *(row(session_id, "Technical fact.", cwd=f"/verified/{index}") for index in range(8)))
    store.repo_resolver = lambda path: {"repo": path.rsplit("/", 1)[-1], "root": path + "/long" * 1000}
    page = store.read(session_id, str(parent))
    assert page["status"] == "ready", page
    assert len(page["verified_repos"]) == 8
    assert all(scope["paths_omitted"] for scope in page["verified_repos"])
    assert len(json.dumps(page, ensure_ascii=True).encode("ascii")) <= MAX_OUTPUT_BYTES


def test_growing_parent_does_not_starve_child_sources(capture):
    store, session_id, parent, _ = capture
    child = parent.with_suffix("") / "subagents" / "agent-child.jsonl"
    write_rows(child, row(session_id, "Child must be processed.", agent_id="child"))
    write_rows(parent, row(session_id, "Large parent finding. " * 1000))
    page = store.read(session_id, str(parent))
    store.acknowledge(session_id, page["receipt"], "nothing_to_save")
    with parent.open("a") as stream:
        stream.write(json.dumps(row(session_id, "Parent continues growing.")) + "\n")
    following = store.read(session_id, str(parent))
    assert following["source"].endswith("agent-child.jsonl")
    assert following["untrusted_context"][0]["text"] == "Child must be processed."


def test_credential_spanning_page_boundary_is_masked_before_splitting(capture):
    store, session_id, parent, _ = capture
    secret = "sk-" + "X" * 10000
    write_rows(parent, row(session_id, "Technical finding.\n" + secret))
    outputs = []
    for _ in range(20):
        page = store.read(session_id, str(parent))
        if page["status"] == "caught_up":
            break
        assert page["status"] == "ready"
        outputs.extend(fragment["text"] for fragment in page["untrusted_context"])
        store.acknowledge(session_id, page["receipt"], "nothing_to_save")
    assert "X" not in "".join(outputs)
    assert "Technical finding" in "".join(outputs)


@pytest.mark.parametrize("bad_ack", [False, [], {"receipt": "x", "outcome": "saved", "memory_ids": "bad"},
                                    {"receipt": "x", "outcome": [], "memory_ids": []}])
def test_corrupt_ack_state_is_rejected(capture, bad_ack):
    store, session_id, parent, state = capture
    state.mkdir()
    path = state / f"{session_id}.json"
    path.write_text(json.dumps({"version": 1, "session_id": session_id, "files": {}, "last_ack": bad_ack}))
    assert store.read(session_id, str(parent))["error_code"] == "invalid_acknowledgement_state"


def test_time_budget_failure_does_not_commit_candidate_progress(capture):
    store, session_id, parent, state = capture
    page = store.read(session_id, str(parent))
    ticks = iter([0, 10])
    store.clock = lambda: next(ticks)
    assert store.acknowledge(session_id, page["receipt"], "nothing_to_save")["error_code"] == "helper_time_budget_exceeded"
    value = read_state(state, session_id)
    assert value["files"] == {}
    assert value["pending"]["receipt"] == page["receipt"]


def test_failed_state_write_does_not_commit_acknowledgement(capture, monkeypatch):
    store, session_id, parent, state = capture
    page = store.read(session_id, str(parent))
    original = store._save
    attempts = []

    def fail_first_write(value):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("Synthetic persistence failure")
        return original(value)

    monkeypatch.setattr(store, "_save", fail_first_write)
    assert store.acknowledge(session_id, page["receipt"], "nothing_to_save")["status"] == "error"
    value = read_state(state, session_id)
    assert value["files"] == {}
    assert value["pending"]["receipt"] == page["receipt"]


def test_changed_giant_record_after_ack_cannot_mix_versions(capture):
    store, session_id, parent, state = capture
    write_rows(parent, row(session_id, "Original record. " * 1000))
    page = store.read(session_id, str(parent))
    store.acknowledge(session_id, page["receipt"], "nothing_to_save")
    before = read_state(state, session_id)["files"]
    parent.write_bytes(parent.read_bytes().replace(b"Original", b"Replaced"))
    assert store.read(session_id, str(parent))["error_code"] == "acknowledged_source_changed"
    assert read_state(state, session_id)["files"] == before


def test_append_after_snapshot_is_reported_as_remaining_on_replay(capture):
    store, session_id, parent, _ = capture
    page = store.read(session_id, str(parent))
    assert page["remaining"] is False
    with parent.open("a") as stream:
        stream.write(json.dumps(row(session_id, "More work.")) + "\n")
    replay = store.read(session_id, str(parent))
    assert replay["receipt"] == page["receipt"]
    assert replay["remaining"] is True


def test_current_message_saves_have_separate_receipt_without_disk_progress(capture):
    store, session_id, parent, state = capture
    page = store.read(session_id, str(parent))
    memory_id = str(uuid.uuid4())
    result = store.record_current(session_id, [memory_id])
    assert result == {"status": "current_saved", "memory_ids": [memory_id]}
    value = read_state(state, session_id)
    assert value["files"] == {}
    assert value["pending"]["receipt"] == page["receipt"]
    assert store.status(session_id)["current_capture"] == {
        "memory_ids": [memory_id], "evidence_kind": "hook_last_assistant_message"}


def test_explicit_empty_repo_roots_do_not_fall_back_to_home(capture, tmp_path):
    _, session_id, parent, state = capture
    store = CaptureStore(parent.parent.parent, state, allowed_repo_roots=())
    write_rows(parent, row(session_id, cwd=str(tmp_path)))
    assert store.read(session_id, str(parent))["verified_repos"] == []


def test_tool_paths_resolve_scope_under_nongit_cwd_and_survive_later_pages(capture, tmp_path):
    store, session_id, parent, _ = capture
    repository = tmp_path / "technical-project"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    source_file = repository / "app.py"
    source_file.write_text("print('synthetic')\n")
    tool = row(session_id, cwd=parent.parent)
    tool["message"]["content"] = [{"type": "tool_use", "id": "tool-one", "name": "Read", "input": {"file_path": str(source_file)}}]
    write_rows(parent, tool, row(session_id, "Technical facts. " * 1000, cwd=parent.parent))
    page = store.read(session_id, str(parent))
    assert page["status"] == "ready"
    assert [scope["repo"] for scope in page["verified_repos"]] == ["technical-project"]
    assert page["verified_repos"][0]["current_page"] is True
    store.acknowledge(session_id, page["receipt"], "nothing_to_save")
    following = store.read(session_id, str(parent))
    assert [scope["repo"] for scope in following["verified_repos"]] == ["technical-project"]
    assert following["verified_repos"][0]["current_page"] is False


def test_caught_up_scope_snapshot_supports_a_late_last_assistant_message(capture, tmp_path):
    store, session_id, parent, _ = capture
    repository = tmp_path / "technical-project"
    repository.mkdir()
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    write_rows(parent, row(session_id, cwd=repository))
    page = store.read(session_id, str(parent))
    store.acknowledge(session_id, page["receipt"], "nothing_to_save")
    following = store.read(session_id, str(parent))
    assert following["status"] == "caught_up"
    assert following["verified_repos"][0]["repo"] == "technical-project"
    assert following["verified_repos"][0]["current_page"] is False


def test_multimegabyte_jsonl_omits_huge_tool_payloads_with_complete_coverage(capture):
    store, session_id, parent, _ = capture
    payload = "SENSITIVE_SYNTHETIC_TOOL_PAYLOAD" + "x" * 100000
    tool_rows = [{"type": "user", "sessionId": session_id, "uuid": str(uuid.uuid4()),
                  "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "synthetic", "content": payload}]}}
                 for _ in range(32)]
    write_rows(parent, row(session_id, "The source identity check is verified."), *tool_rows)
    assert parent.stat().st_size > 2.8 * 1024 * 1024
    page = store.read(session_id, str(parent))
    assert page["status"] == "ready", page
    encoded = json.dumps(page, ensure_ascii=True)
    assert len(encoded.encode("ascii")) <= MAX_OUTPUT_BYTES
    assert "SENSITIVE_SYNTHETIC_TOOL_PAYLOAD" not in encoded
    assert [fragment["text"] for fragment in page["untrusted_context"]] == ["The source identity check is verified."]
    assert page["source_complete"] is True
    store.acknowledge(session_id, page["receipt"], "nothing_to_save")
    assert store.read(session_id, str(parent))["status"] == "caught_up"
