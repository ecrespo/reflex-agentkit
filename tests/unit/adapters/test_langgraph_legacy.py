"""``legacy_interrupts=True``: the ``on_interrupt`` CUSTOM channel (T-045, REQ-034.5)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    ResumeEntry,
    RunAgentInput,
    RunFinishedEvent,
    UserMessage,
)
from ag_ui_langgraph import LangGraphAgent
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent

answers: list[Any] = []


@pytest.fixture(autouse=True)
def _reset() -> None:
    answers.clear()


def _graph(*values: Any) -> Any:
    builder = StateGraph(MessagesState)
    for index, value in enumerate(values):
        node = f"n{index}"

        def ask(state: MessagesState, value: Any = value) -> dict[str, Any]:
            answers.append(interrupt(value))
            return {"messages": [AIMessage(content="ok", id=f"ai-{len(answers)}")]}

        builder.add_node(node, ask)
        builder.add_edge(START, node)
        builder.add_edge(node, END)
    return builder.compile(checkpointer=InMemorySaver())


def _input(run_id: str, resume: list[ResumeEntry] | None = None) -> RunAgentInput:
    return RunAgentInput(
        thread_id="t1",
        run_id=run_id,
        messages=[UserMessage(id="u1", role="user", content="go")],
        tools=[],
        context=[],
        state={},
        forwarded_props={},
        resume=resume,
    )


async def _run(agent: LangGraphAGUIAgent, run_input: RunAgentInput) -> list[BaseEvent]:
    return [event async for event in agent.run(run_input)]


def test_REQ_034_5_legacy_mode_flips_the_interrupt_flags() -> None:
    agent = LangGraphAGUIAgent(_graph("q"), legacy_interrupts=True)
    assert agent.enable_legacy_on_interrupt_event is True
    assert agent.emit_interrupt_outcome is False
    assert agent.clone().legacy_interrupts is True


async def test_REQ_034_5_on_interrupt_becomes_a_standard_interrupt_outcome() -> None:
    """REQ-034.5, DD-012: no CUSTOM event; a synthetic, stateless interrupt ID."""
    value = {"reason": "confirm", "message": "Proceed?", "extra": 1}
    events = await _run(LangGraphAGUIAgent(_graph(value), legacy_interrupts=True), _input("r1"))
    assert not any(isinstance(e, CustomEvent) and e.name == "on_interrupt" for e in events)
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert finished.outcome is not None and finished.outcome.type == "interrupt"
    [mapped] = finished.outcome.interrupts
    assert (mapped.id, mapped.reason, mapped.message) == ("legacy-r1", "confirm", "Proceed?")
    assert mapped.metadata == {"langgraph": {"raw": value}}


async def test_REQ_034_5_tool_call_values_get_the_tool_prefix() -> None:
    value = {"reason": "tool_call", "toolCallId": "c1", "message": "Approve?"}
    events = await _run(LangGraphAGUIAgent(_graph(value), legacy_interrupts=True), _input("r1"))
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent) and finished.outcome is not None
    [mapped] = finished.outcome.interrupts  # type: ignore[union-attr]
    assert (mapped.id, mapped.tool_call_id) == ("legacy-tool-r1", "c1")


async def test_REQ_034_5_string_values_become_the_message() -> None:
    events = await _run(LangGraphAGUIAgent(_graph("Sure?"), legacy_interrupts=True), _input("r1"))
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent) and finished.outcome is not None
    [mapped] = finished.outcome.interrupts  # type: ignore[union-attr]
    assert (mapped.reason, mapped.message) == ("langgraph:interrupt", "Sure?")


async def test_REQ_034_5_resume_goes_through_forwarded_props(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DD-012: ``resume[]`` becomes ``forwarded_props.command.resume``."""
    agent = LangGraphAGUIAgent(_graph({"reason": "confirm"}), legacy_interrupts=True)
    await _run(agent, _input("r1"))
    inputs: list[RunAgentInput] = []
    original = LangGraphAgent.run

    def spy(self: Any, run_input: RunAgentInput) -> Any:
        inputs.append(run_input)
        return original(self, run_input)

    monkeypatch.setattr(LangGraphAgent, "run", spy)
    entry = ResumeEntry(interrupt_id="legacy-r1", status="resolved", payload={"ok": True})
    events = await _run(agent, _input("r2", [entry]))
    assert inputs[0].resume is None
    assert inputs[0].forwarded_props == {"command": {"resume": {"ok": True}}}
    assert answers == [{"ok": True}]
    assert isinstance(events[-1], RunFinishedEvent)
    assert events[-1].outcome is None or events[-1].outcome.type == "success"


@pytest.mark.parametrize(
    ("interrupt_id", "expected"),
    [
        ("legacy-tool-r1", {"approved": False, "reason": "cancelled"}),
        ("legacy-r1", {"__agui_cancelled__": True, "interrupt_id": "legacy-r1"}),
    ],
)
async def test_REQ_034_5_cancelled_entries_resume_like_the_native_mode(
    interrupt_id: str, expected: dict[str, Any]
) -> None:
    value = {"reason": "tool_call" if "tool" in interrupt_id else "confirm", "toolCallId": "c1"}
    agent = LangGraphAGUIAgent(_graph(value), legacy_interrupts=True)
    await _run(agent, _input("r1"))
    await _run(agent, _input("r2", [ResumeEntry(interrupt_id=interrupt_id, status="cancelled")]))
    assert answers == [expected]


async def test_REQ_034_5_only_the_first_interrupt_is_exposed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DD-012: the legacy channel carries one resume value."""
    agent = LangGraphAGUIAgent(_graph("first?", "second?"), legacy_interrupts=True)
    with caplog.at_level(logging.WARNING, logger="reflex_agentkit.adapters.langgraph"):
        events = await _run(agent, _input("r1"))
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent) and finished.outcome is not None
    assert len(finished.outcome.interrupts) == 1  # type: ignore[union-attr]
    assert any("dropped 1" in r.getMessage() for r in caplog.records)
    assert all("second?" not in r.getMessage() for r in caplog.records)
