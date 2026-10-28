from __future__ import annotations

import pytest

from services.chat.participants import ChatParticipant, chat_participants, find_participant

REGISTRY_ENV = {
    "CHAT_MODEL_NAMES": "Kimi, Qwen",
    "CHAT_KIMI_MODEL_ID": "moonshotai.kimi-k2.5",
    "CHAT_QWEN_MODEL_ID": "qwen.qwen3-max",
}


def registry(**overrides: str | None) -> dict[str, str]:
    merged = {**REGISTRY_ENV, **overrides}
    return {name: value for name, value in merged.items() if value is not None}


@pytest.fixture
def _registry_os_env(monkeypatch):
    monkeypatch.delenv("CHAT_MODEL_IDS", raising=False)
    for name, value in REGISTRY_ENV.items():
        monkeypatch.setenv(name, value)


def test_participants_become_chat_model_roles_in_registry_order():
    assert chat_participants(registry()) == [
        ChatParticipant(name="Kimi", model_role="chat_kimi"),
        ChatParticipant(name="Qwen", model_role="chat_qwen"),
    ]


def test_multi_word_names_map_to_one_settings_prefix():
    participants = chat_participants(
        registry(CHAT_MODEL_NAMES="Kimi K3", CHAT_KIMI_K3_MODEL_ID="us.moonshotai.kimi-k3")
    )

    assert participants == [ChatParticipant(name="Kimi K3", model_role="chat_kimi_k3")]


def test_participant_model_can_come_from_a_preset():
    participants = chat_participants(
        registry(
            CHAT_KIMI_MODEL_ID=None,
            CHAT_KIMI_MODEL_PRESET="KIMI_K2_5",
            KIMI_K2_5_MODEL_ID="moonshotai.kimi-k2.5",
        )
    )

    assert participants[0] == ChatParticipant(name="Kimi", model_role="chat_kimi")


def test_participant_without_a_model_is_rejected():
    with pytest.raises(ValueError) as failure:
        chat_participants(registry(CHAT_MODEL_NAMES="Kimi,Bard"))

    message = str(failure.value)
    assert "Graph model role 'chat_bard' has no MODEL_ID configured" in message
    assert "CHAT_BARD_MODEL_PRESET" in message


def test_participant_with_an_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="no NOPE_MODEL_\\* settings are defined"):
        chat_participants(registry(CHAT_KIMI_MODEL_PRESET="NOPE"))


def test_obsolete_index_aligned_model_ids_are_rejected():
    with pytest.raises(ValueError, match="CHAT_MODEL_IDS is obsolete"):
        chat_participants(registry(CHAT_MODEL_IDS="moonshotai.kimi-k2.5,qwen.qwen3-max"))


def test_names_sharing_a_settings_prefix_are_rejected():
    with pytest.raises(ValueError, match="would both read CHAT_KIMI_K3_MODEL_\\* settings"):
        chat_participants(
            registry(CHAT_MODEL_NAMES="Kimi K3,Kimi-K3", CHAT_KIMI_K3_MODEL_ID="us.moonshotai.kimi-k3")
        )


def test_name_without_letters_or_digits_is_rejected():
    with pytest.raises(ValueError, match="needs letters or digits"):
        chat_participants(registry(CHAT_MODEL_NAMES="Kimi,!!!"))


def test_find_participant_is_case_insensitive(_registry_os_env):
    assert find_participant("kImI").model_role == "chat_kimi"
    assert find_participant(" QWEN ").name == "Qwen"


def test_unknown_participant_error_lists_valid_names(_registry_os_env):
    with pytest.raises(ValueError, match=r"unknown chat participant.*Kimi, Qwen"):
        find_participant("Bard")


@pytest.mark.parametrize("names", ["Kimi,kimi", "Kimi,KIMI"])
def test_case_insensitive_duplicate_names_are_rejected(names):
    with pytest.raises(ValueError, match="duplicate name"):
        chat_participants(registry(CHAT_MODEL_NAMES=names))


@pytest.mark.parametrize("reserved", ["user", "claude", "Codex", "GEMINI"])
def test_reserved_identities_are_rejected(reserved):
    with pytest.raises(ValueError, match="reserved identity"):
        chat_participants(registry(CHAT_MODEL_NAMES=f"Kimi,{reserved}"))


@pytest.mark.parametrize("names", [" , ", None])
def test_missing_or_blank_name_list_is_rejected(names):
    with pytest.raises(ValueError, match="non-empty comma-separated list"):
        chat_participants(registry(CHAT_MODEL_NAMES=names))


def test_overlong_name_is_rejected():
    with pytest.raises(ValueError, match="64 characters or fewer"):
        chat_participants(registry(CHAT_MODEL_NAMES="Kimi," + "x" * 65))
