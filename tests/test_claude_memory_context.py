from __future__ import annotations

import json
import uuid

import pytest

from scripts import claude_memory_context
from scripts.claude_memory_context import probe
from scripts.shared.claude_memory_capture import CaptureStore


def test_probe_records_nonce_for_verified_execution(tmp_path):
    session_id = str(uuid.uuid4())
    result = probe(session_id, tmp_path)
    assert result["status"] == "probe_ready"
    assert len(result["nonce"]) == 32
    assert json.loads((tmp_path / "probes" / f"{session_id}.json").read_text()) == result


def test_probe_rejects_invalid_session_before_writing(tmp_path):
    with pytest.raises(ValueError):
        probe("../../elsewhere", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cli_read_ack_and_current_receipts_use_production_store(tmp_path, monkeypatch, capsys):
    session_id = str(uuid.uuid4())
    logs = tmp_path / "logs"
    parent = logs / "project" / f"{session_id}.jsonl"
    parent.parent.mkdir(parents=True)
    parent.write_text(json.dumps({"type": "assistant", "sessionId": session_id, "uuid": "message-one",
                                 "message": {"role": "assistant", "content": "Verified synthetic technical fact."}}) + "\n")
    store = CaptureStore(logs, tmp_path / "state", allowed_repo_roots=())
    monkeypatch.setattr(claude_memory_context, "CaptureStore", lambda *_: store)
    assert claude_memory_context.main(["read", "--session-id", session_id, "--transcript", str(parent)]) == 0
    page = json.loads(capsys.readouterr().out)
    assert page["status"] == "ready"
    memory_id = str(uuid.uuid4())
    assert claude_memory_context.main(["ack", "--session-id", session_id, "--receipt", page["receipt"],
                                       "--outcome", "saved", "--memory-id", memory_id]) == 0
    assert json.loads(capsys.readouterr().out)["memory_ids"] == [memory_id]
    assert claude_memory_context.main(["record-current", "--session-id", session_id, "--memory-id", memory_id]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "current_saved"
    assert claude_memory_context.main(["status", "--session-id", session_id]) == 0
    assert json.loads(capsys.readouterr().out)["current_capture"]["memory_ids"] == [memory_id]
