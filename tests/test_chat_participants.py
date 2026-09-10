from __future__ import annotations

import pytest

from services.chat.participants import ChatParticipant, chat_participants, find_participant


@pytest.fixture(autouse=True)
def _registry_env(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL_NAMES", "Kimi, Qwen")
    monkeypatch.setenv("CHAT_MODEL_IDS", "moonshotai.kimi-k2.5, qwen.qwen3-max")


def test_parses_ordered_index_aligned_pairs():
    assert chat_participants() == [
        ChatParticipant(name="Kimi", model_id="moonshotai.kimi-k2.5"),
        ChatParticipant(name="Qwen", model_id="qwen.qwen3-max"),
    ]


def test_find_participant_is_case_insensitive():
    assert find_participant("kImI").model_id == "moonshotai.kimi-k2.5"
    assert find_participant(" QWEN ").name == "Qwen"


def test_unknown_participant_error_lists_valid_names():
    with pytest.raises(ValueError, match=r"unknown chat participant.*Kimi, Qwen"):
        find_participant("Bard")


def test_length_mismatch_is_rejected(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL_IDS", "moonshotai.kimi-k2.5")
    with pytest.raises(ValueError, match="equal length"):
        chat_participants()


@pytest.mark.parametrize("names", ["Kimi,kimi", "Kimi,KIMI"])
def test_case_insensitive_duplicate_names_are_rejected(monkeypatch, names):
    monkeypatch.setenv("CHAT_MODEL_NAMES", names)
    with pytest.raises(ValueError, match="duplicate name"):
        chat_participants()


@pytest.mark.parametrize("reserved", ["user", "claude", "Codex", "GEMINI"])
def test_reserved_identities_are_rejected(monkeypatch, reserved):
    monkeypatch.setenv("CHAT_MODEL_NAMES", f"Kimi,{reserved}")
    with pytest.raises(ValueError, match="reserved identity"):
        chat_participants()


@pytest.mark.parametrize("var", ["CHAT_MODEL_NAMES", "CHAT_MODEL_IDS"])
def test_missing_or_blank_lists_are_rejected(monkeypatch, var):
    monkeypatch.setenv(var, " , ")
    with pytest.raises(ValueError, match="non-empty comma-separated list"):
        chat_participants()


def test_overlong_name_is_rejected(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL_NAMES", "Kimi," + "x" * 65)
    with pytest.raises(ValueError, match="64 characters or fewer"):
        chat_participants()
