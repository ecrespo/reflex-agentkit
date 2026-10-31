"""The PydanticAI Dojo: five demos, sized, compiled and driven offline (T-047, REQ-030)."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from helpers.dojo import DEMOS, ROOT, compile_offline, counted_lines
from helpers.reflex_harness import ReflexHarness

from reflex_agentkit.core.models import RunStatus, ToolCallStatus

EXAMPLE = ROOT / "examples" / "pydantic_ai_dojo"
PACKAGE = EXAMPLE / "pydantic_ai_dojo"


@pytest.mark.parametrize("demo", DEMOS)
def test_REQ_030_1_each_demo_has_50_to_200_lines(demo: str) -> None:
    """REQ-030.1: one module per demo, 50-200 counted lines."""
    assert 50 <= counted_lines(PACKAGE / "demos" / f"{demo}.py") <= 200


@pytest.mark.slow
def test_REQ_030_2_the_dojo_compiles_without_network_or_keys() -> None:
    """REQ-030.2: a compile smoke test with the test model."""
    result = compile_offline(EXAMPLE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "compiled successfully" in result.stdout


@pytest.fixture
def demos(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setenv("AGENTKIT_MODEL", "test")
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    monkeypatch.syspath_prepend(str(EXAMPLE))

    def load(demo: str) -> ModuleType:
        return importlib.import_module(f"pydantic_ai_dojo.demos.{demo}")

    yield load


async def test_REQ_030_1_human_in_the_loop_asks_before_booking(
    demos: Any, reflex_harness: ReflexHarness
) -> None:
    state_cls = demos("human_in_the_loop").HumanInTheLoopState
    await reflex_harness.call("hitl", state_cls, "send_message", text="Book me a flight")
    state = await reflex_harness.state("hitl", state_cls)
    assert state.run_status == RunStatus.AWAITING_INPUT, state.error
    [call] = state.pending_approvals
    await reflex_harness.call("hitl", state_cls, "approve_tool", call_id=call.id)
    state = await reflex_harness.state("hitl", state_cls)
    assert state.run_status == RunStatus.IDLE, state.error
    assert next(c for c in state.tool_calls if c.id == call.id).status == ToolCallStatus.DONE


async def test_REQ_030_1_shared_state_is_written_by_the_agent(
    demos: Any, reflex_harness: ReflexHarness
) -> None:
    state_cls = demos("shared_state").SharedStateState
    await reflex_harness.call("shared", state_cls, "send_message", text="A pasta recipe")
    state = await reflex_harness.state("shared", state_cls)
    assert state.run_status == RunStatus.IDLE, state.error
    assert set(state.shared_state) >= {"title", "ingredients", "steps"}
    assert state.typed_shared_state() is not None


async def test_REQ_030_1_generative_ui_runs_the_client_tool(
    demos: Any, reflex_harness: ReflexHarness
) -> None:
    state_cls = demos("generative_ui").GenerativeUIState
    await reflex_harness.call("genui", state_cls, "send_message", text="Chart my week")
    state = await reflex_harness.state("genui", state_cls)
    assert state.run_status == RunStatus.IDLE, state.error
    chart = next(c for c in state.tool_calls if c.name == "show_chart")
    assert chart.is_client_tool
    assert chart.status == ToolCallStatus.DONE


async def test_REQ_030_1_backend_tool_result_is_rendered(
    demos: Any, reflex_harness: ReflexHarness
) -> None:
    module = demos("backend_tools")
    await reflex_harness.call("tools", module.BackendToolsState, "send_message", text="Weather?")
    state = await reflex_harness.state("tools", module.BackendToolsState)
    assert state.run_status == RunStatus.IDLE, state.error
    weather = next(c for c in state.tool_calls if c.name == "get_weather")
    assert weather.status == ToolCallStatus.DONE
    assert "get_weather" in module.TOOL_RENDERERS


async def test_REQ_030_1_agentic_chat_streams_a_reply(
    demos: Any, reflex_harness: ReflexHarness
) -> None:
    state_cls = demos("agentic_chat").AgenticChatState
    await reflex_harness.call("chat", state_cls, "send_message", text="Hello")
    state = await reflex_harness.state("chat", state_cls)
    assert state.run_status == RunStatus.IDLE, state.error
    assert state.messages[-1].role == "assistant"
    assert state.messages[-1].content
