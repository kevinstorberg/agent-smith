import json
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from config.loader import load_default_config
from config.models import LLMConfig


def build_llm(
    *,
    provider: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    config: LLMConfig | None = None,
) -> Any:
    """Build an LLM instance.

    Resolution order for each parameter: explicit arg > config arg > default.yaml
    """
    default = load_default_config().llm

    resolved_provider = provider or (config.provider if config else None) or default.provider
    resolved_model = model or (config.model if config else None) or default.model
    resolved_max_tokens = max_tokens or (config.max_tokens if config else None) or default.max_tokens

    if resolved_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=resolved_model, max_tokens=resolved_max_tokens)

    if resolved_provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=resolved_model, max_tokens=resolved_max_tokens)

    if resolved_provider == "fake":
        return DeterministicFakeChatModel(model=resolved_model, max_tokens=resolved_max_tokens)

    raise ValueError(f"Unknown LLM provider: {resolved_provider!r}. Available: anthropic, openai, fake")


class DeterministicFakeChatModel(BaseChatModel):
    model: str = "fake"
    max_tokens: int = 4096
    tool_names: tuple[str, ...] = ()

    @property
    def _llm_type(self) -> str:
        return "agent_smith_fake"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> "DeterministicFakeChatModel":
        return self.model_copy(update={"tool_names": tuple(_tool_name(tool) for tool in tools)})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._content(messages)))])

    def _content(self, messages: Any) -> str:
        payload = {
            "provider": "fake",
            "model": self.model,
            "tools": list(self.tool_names),
            "input": _last_message_content(messages),
        }
        return json.dumps(payload, sort_keys=True)


def _tool_name(tool: dict[str, Any] | type | Callable | Any) -> str:
    if isinstance(tool, dict):
        return str(tool.get("name") or tool.get("title") or "tool")
    name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
    return str(name or tool.__class__.__name__)


def _last_message_content(messages: Any) -> str:
    if isinstance(messages, dict):
        messages = messages.get("messages", messages)
    if not isinstance(messages, list | tuple) or not messages:
        return str(messages)
    message = messages[-1]
    return str(getattr(message, "content", message))
