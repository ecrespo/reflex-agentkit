"""Model selection for the examples (T-046, REQ-030.2): Claude, Ollama or a test model."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.test import TestModel

SHARED = Path(__file__).resolve().parents[3] / "examples" / "_shared"


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    monkeypatch.syspath_prepend(str(SHARED))
    monkeypatch.delenv("AGENTKIT_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-used")
    from examples_shared import models

    yield models


def test_REQ_030_2_pydantic_ai_defaults_to_claude(models: ModuleType) -> None:
    assert models.pydantic_ai_model() == "anthropic:claude-sonnet-5-5"


def test_REQ_030_2_pydantic_ai_test_model(
    models: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTKIT_MODEL", "test")
    assert isinstance(models.pydantic_ai_model(), TestModel)


def test_REQ_030_2_pydantic_ai_ollama_uses_the_openai_compatible_api(
    models: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTKIT_MODEL", "ollama:qwen3")
    model = models.pydantic_ai_model()
    assert isinstance(model, OllamaModel)
    assert model.model_name == "qwen3"
    assert str(model.base_url).rstrip("/") == "http://localhost:11434/v1"
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box:11434/v1")
    assert str(models.pydantic_ai_model().base_url).rstrip("/") == "http://gpu-box:11434/v1"


def test_REQ_030_2_other_model_strings_pass_through(
    models: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTKIT_MODEL", "anthropic:claude-opus-5-5")
    assert models.pydantic_ai_model() == "anthropic:claude-opus-5-5"


def test_REQ_030_2_ollama_needs_a_model_name(
    models: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTKIT_MODEL", "ollama:")
    with pytest.raises(ValueError, match="ollama:<model>"):
        models.pydantic_ai_model()
    with pytest.raises(ValueError, match="ollama:<model>"):
        models.langgraph_model()


def test_REQ_030_2_langgraph_defaults_to_claude(models: ModuleType) -> None:
    model = models.langgraph_model()
    assert isinstance(model, ChatAnthropic)
    assert model.model == "claude-sonnet-5-5"


def test_REQ_030_2_langgraph_ollama(models: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKIT_MODEL", "ollama:qwen3")
    model = models.langgraph_model()
    assert isinstance(model, ChatOpenAI)
    assert (model.model_name, model.openai_api_base) == ("qwen3", "http://localhost:11434/v1")


async def test_REQ_030_2_langgraph_test_model_answers_offline_and_binds_tools(
    models: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTKIT_MODEL", "test")
    model = models.langgraph_model()
    assert isinstance(model, BaseChatModel)
    bound = model.bind_tools([])
    reply = await bound.ainvoke([HumanMessage(content="hi")])
    assert reply.content
