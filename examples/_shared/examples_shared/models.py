"""Pick the examples' model from ``AGENTKIT_MODEL`` (REQ-030.2).

- unset: Claude (``claude-sonnet-5-5``), which needs ``ANTHROPIC_API_KEY``;
- ``ollama:<model>``: a local Ollama model through its OpenAI-compatible API at
  ``OLLAMA_BASE_URL`` (default ``http://localhost:11434/v1``);
- ``test``: an offline test model, used by CI;
- anything else (PydanticAI only): passed through as a PydanticAI model name.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from typing import Any

CLAUDE_MODEL = "claude-sonnet-5-5"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_PREFIX = "ollama:"


def selected_model() -> str:
    """The value of ``AGENTKIT_MODEL``, or ``""`` for the default (Claude)."""
    return os.environ.get("AGENTKIT_MODEL", "").strip()


def ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL


def _ollama_name(choice: str) -> str:
    name = choice.removeprefix(OLLAMA_PREFIX).strip()
    if not name:
        raise ValueError("AGENTKIT_MODEL must name the model: ollama:<model>, e.g. ollama:qwen3")
    return name


def pydantic_ai_model() -> Any:
    """A PydanticAI model, or model name, for ``pydantic_ai.Agent``."""
    choice = selected_model()
    if not choice:
        return f"anthropic:{CLAUDE_MODEL}"
    if choice == "test":
        from pydantic_ai.models.test import TestModel

        return TestModel()
    if choice.startswith(OLLAMA_PREFIX):
        from pydantic_ai.models.ollama import OllamaModel
        from pydantic_ai.providers.ollama import OllamaProvider

        provider = OllamaProvider(base_url=ollama_base_url())
        return OllamaModel(_ollama_name(choice), provider=provider)
    return choice


def langgraph_model() -> Any:
    """A LangChain chat model for the LangGraph examples."""
    choice = selected_model()
    if not choice:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model_name=CLAUDE_MODEL, timeout=None, stop=None)
    if choice == "test":
        return _offline_chat_model()
    if choice.startswith(OLLAMA_PREFIX):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=_ollama_name(choice), base_url=ollama_base_url(), api_key="ollama")
    raise ValueError(f"AGENTKIT_MODEL={choice!r}: use ollama:<model>, test, or leave it unset")


def _offline_chat_model() -> Any:
    """A chat model that always answers with one short text, and accepts ``bind_tools``."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    class OfflineChatModel(GenericFakeChatModel):
        def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> OfflineChatModel:
            return self

    def replies() -> Iterator[AIMessage]:
        while True:
            yield AIMessage(content="This is an offline test reply.")

    return OfflineChatModel(messages=replies())
