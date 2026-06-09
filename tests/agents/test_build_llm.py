from unittest.mock import patch

import pytest

from config.models import LLMConfig
from src.agents.llm import DeterministicFakeChatModel, build_llm


@pytest.mark.unit
class TestBuildLlm:
    @patch("langchain_anthropic.ChatAnthropic")
    def test_defaults_from_yaml_config(self, mock_anthropic):
        build_llm()
        mock_anthropic.assert_called_once()
        call_kwargs = mock_anthropic.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["max_tokens"] == 4096

    @patch("langchain_openai.ChatOpenAI")
    def test_explicit_provider_override(self, mock_openai):
        build_llm(provider="openai", model="gpt-4o")
        mock_openai.assert_called_once()
        assert mock_openai.call_args[1]["model"] == "gpt-4o"

    @patch("langchain_anthropic.ChatAnthropic")
    def test_config_object_used_as_fallback(self, mock_anthropic):
        config = LLMConfig(provider="anthropic", model="claude-haiku-4-5-20251001", max_tokens=1024)
        build_llm(config=config)
        call_kwargs = mock_anthropic.call_args[1]
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert call_kwargs["max_tokens"] == 1024

    @patch("langchain_anthropic.ChatAnthropic")
    def test_explicit_args_override_config(self, mock_anthropic):
        config = LLMConfig(provider="anthropic", model="claude-haiku-4-5-20251001", max_tokens=1024)
        build_llm(model="claude-sonnet-4-6", max_tokens=2048, config=config)
        call_kwargs = mock_anthropic.call_args[1]
        assert call_kwargs["model"] == "claude-sonnet-4-6"
        assert call_kwargs["max_tokens"] == 2048

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="Available: anthropic, openai, fake"):
            build_llm(provider="gemini")

    def test_fake_provider_returns_deterministic_chat_model(self):
        llm = build_llm(provider="fake", model="local-fake", max_tokens=64)

        assert isinstance(llm, DeterministicFakeChatModel)
        assert llm.model == "local-fake"
        assert llm.max_tokens == 64

    def test_fake_provider_supports_tool_binding(self):
        llm = build_llm(provider="fake")

        bound = llm.bind_tools([{"name": "summarize_project"}])

        assert isinstance(bound, DeterministicFakeChatModel)
        assert bound.tool_names == ("summarize_project",)
