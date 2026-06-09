import pytest

from config.prompts import loader


def test_load_prompt_reads_txt_file_and_strips_whitespace(monkeypatch, tmp_path):
    prompt_path = tmp_path / "system.txt"
    prompt_path.write_text("\n  You are a useful assistant.  \n")
    monkeypatch.setattr(loader, "_PROMPTS_DIR", tmp_path)

    assert loader.load_prompt("system") == "You are a useful assistant."


def test_load_prompt_raises_for_missing_prompt(monkeypatch, tmp_path):
    monkeypatch.setattr(loader, "_PROMPTS_DIR", tmp_path)

    with pytest.raises(FileNotFoundError, match="Prompt file not found"):
        loader.load_prompt("missing")
