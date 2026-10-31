"""The LangGraph Dojo: five demos, sized, compiled and driven offline (T-048, REQ-030).

Each demo module exposes ``build_graph(model)``; the driven tests swap the state's agent
for the same graph on a scripted chat model, so the real graph logic runs offline.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterator
from types import ModuleType
from typing import Any

import pytest
from helpers.dojo import DEMOS, ROOT, compile_offline, counted_lines
from helpers.fake_chat_model import ScriptedChatModel
from helpers.reflex_harness import ReflexHarness
from langchain_core.messages import AIMessage

from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent
from reflex_agentkit.core.models import RunStatus, ToolCallStatus

EXAMPLE = ROOT / "examples" / "langgraph_dojo"
PACKAGE = EXAMPLE / "langgraph_dojo"

Loader = Callable[[str, list[AIMessage]], tuple[ModuleType, Any]]


def _call(name: str, args: dict[str, Any], call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="", id=f"ai-{call_id}", tool_calls=[{"id": call_id, "name": name, "args": args}]
    )


def _say(text: str, message_id: str = "ai-final") -> AIMessage:
    return AIMessage(content=text, id=message_id)


@pytest.mark.parametrize("demo", DEMOS)
def test_REQ_030_1_each_demo_has_50_to_200_lines(demo: str) -> None:
    """REQ-030.1: one module per demo, 50-200 counted lines."""
    assert 50 <= counted_lines(PACKAGE / "demos" / f"{demo}.py") <= 200


@pytest.mark.slow
def test_REQ_030_2_the_dojo_compiles_without_network_or_keys() -> None:
    """REQ-030.2: a compile smoke test with the offline model."""
    result = compile_offline(EXAMPLE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "compiled successfully" in result.stdout


@pytest.fixture
def demo(monkeypatch: pytest.MonkeyPatch) -> Iterator[Loader]:
    """Import a demo and point its state at a graph on a scripted model."""
    monkeypatch.setenv("AGENTKIT_MODEL", "test")
    monkeypatch.syspath_prepend(str(EXAMPLE))

    def load(name: str, script: list[AIMessage]) -> tuple[ModuleType, Any]:
        module = importlib.import_module(f"langgraph_dojo.demos.{name}")
        state_cls = module.STATE
        graph = module.build_graph(ScriptedChatModel(script=script))
        monkeypatch.setattr(state_cls, "agent", LangGraphAGUIAgent(graph))
        return module, state_cls

    yield load


async def test_REQ_030_1_agentic_chat_calls_a_tool_and_replies(
    demo: Loader, reflex_harness: ReflexHarness
) -> None:
    _, state_cls = demo(
        "agentic_chat",
        [_call("current_time", {"timezone": "Asia/Tokyo"}), _say("It is late in Tokyo.")],
    )
    await reflex_harness.call("lg-chat", state_cls, "send_message", text="Time in Tokyo?")
    state = await reflex_harness.state("lg-chat", state_cls)
    assert state.run_status == RunStatus.IDLE, state.error
    [call] = state.tool_calls
    assert (call.name, call.status) == ("current_time", ToolCallStatus.DONE)
    assert "Asia/Tokyo" in (call.result or "")
    assert state.messages[-1].content == "It is late in Tokyo."


async def test_REQ_030_1_backend_tool_has_a_renderer(
    demo: Loader, reflex_harness: ReflexHarness
) -> None:
    module, state_cls = demo(
        "backend_tools", [_call("get_weather", {"city": "Oslo"}), _say("Cold in Oslo.")]
    )
    await reflex_harness.call("lg-tools", state_cls, "send_message", text="Weather in Oslo?")
    state = await reflex_harness.state("lg-tools", state_cls)
    assert state.run_status == RunStatus.IDLE, state.error
    assert state.tool_calls[0].status == ToolCallStatus.DONE
    assert '"city": "Oslo"' in (state.tool_calls[0].result or "")
    assert "get_weather" in module.TOOL_RENDERERS


async def test_REQ_030_1_human_in_the_loop_question_then_approval(
    demo: Loader, reflex_harness: ReflexHarness
) -> None:
    """``interrupt()`` for a question, then ``request_tool_approval`` with edits."""
    _, state_cls = demo(
        "human_in_the_loop",
        [
            _call("ask_user", {"question": "How many nights?"}, "q1"),
            _call("book_trip", {"destination": "Kyoto", "nights": 2}, "b1"),
            _say("Booked!"),
        ],
    )
    token = "lg-hitl"  # noqa: S105 - a Reflex client token, not a secret
    await reflex_harness.call(token, state_cls, "send_message", text="Book Kyoto")
    state = await reflex_harness.state(token, state_cls)
    assert state.run_status == RunStatus.AWAITING_INPUT, state.error
    assert state.pending_interrupt is not None
    assert state.pending_interrupt.message == "How many nights?"

    await reflex_harness.call(token, state_cls, "respond_to_interrupt", payload="three")
    state = await reflex_harness.state(token, state_cls)
    assert state.run_status == RunStatus.AWAITING_INPUT, state.error
    [approval] = state.pending_approvals
    assert approval.args == {"destination": "Kyoto", "nights": 2}

    edited = {"destination": "Kyoto", "nights": 3}
    await reflex_harness.call(
        token, state_cls, "approve_tool", call_id=approval.id, edited_args=edited
    )
    state = await reflex_harness.state(token, state_cls)
    assert state.run_status == RunStatus.IDLE, state.error
    question, booking = state.tool_calls
    assert question.result == "three"
    assert booking.status == ToolCallStatus.DONE
    assert "3 night(s) in Kyoto" in (booking.result or "")


async def test_REQ_030_1_shared_state_is_written_by_the_graph_and_read_back(
    demo: Loader, reflex_harness: ReflexHarness
) -> None:
    recipe = {
        "title": "Pasta al limone",
        "servings": 2,
        "ingredients": ["pasta", "lemon"],
        "steps": ["boil", "toss"],
    }
    _, state_cls = demo("shared_state", [_call("update_recipe", recipe), _say("Enjoy!")])
    await reflex_harness.call("lg-shared", state_cls, "send_message", text="A pasta recipe")
    state = await reflex_harness.state("lg-shared", state_cls)
    assert state.run_status == RunStatus.IDLE, state.error
    assert state.shared_state == recipe
    assert state.typed_shared_state().title == "Pasta al limone"


async def test_REQ_030_1_generative_ui_runs_the_client_tool(
    demo: Loader, reflex_harness: ReflexHarness
) -> None:
    chart = {"title": "Week", "labels": ["Mon", "Tue"], "values": [40, 65]}
    _, state_cls = demo("generative_ui", [_call("show_chart", chart), _say("Tuesday peaks.")])
    await reflex_harness.call("lg-genui", state_cls, "send_message", text="Chart my week")
    state = await reflex_harness.state("lg-genui", state_cls)
    assert state.run_status == RunStatus.IDLE, state.error
    [call] = state.tool_calls
    assert call.is_client_tool
    assert call.status == ToolCallStatus.DONE
    assert state.messages[-1].content == "Tuesday peaks."
