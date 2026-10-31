"""Contract tests: ag-ui-langgraph behavior the adapter relies on (TD §8.4 item 3, DD-012).

Pinned against ag-ui-langgraph 0.0.47 and langgraph 1.2 (DD-001). A failure after an
upgrade means DD-012 must be revisited.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from typing import Any

import pytest
from ag_ui.core import (
    BaseEvent,
    Interrupt,
    ResumeEntry,
    RunAgentInput,
    RunFinishedEvent,
    StateSnapshotEvent,
    UserMessage,
)
from ag_ui_langgraph import LangGraphAgent
from ag_ui_langgraph.interrupts import lg_interrupt_to_agui
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, interrupt
from langgraph.types import Interrupt as LangGraphInterrupt

from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent

answers: dict[str, Any] = {}


def _ask(node: str) -> Any:
    def ask(state: MessagesState) -> dict[str, Any]:
        answers[node] = interrupt({"reason": "confirm", "message": f"{node}?"})
        return {"messages": [AIMessage(content=f"{node} ok", id=f"ai-{node}")]}

    return ask


def _graph(*nodes: str) -> Any:
    builder = StateGraph(MessagesState)
    for node in nodes:
        builder.add_node(node, _ask(node))
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


async def _run(agent: Any, run_input: RunAgentInput) -> list[BaseEvent]:
    return [event async for event in agent.run(run_input)]


def test_TD_8_4_3_dict_interrupt_values_map_onto_interrupt_fields() -> None:
    """DD-012 (Q-4): the native keys; the value itself is ``metadata.langgraph.raw``."""
    value = {
        "reason": "tool_call",
        "toolCallId": "c1",
        "message": "Approve?",
        "responseSchema": {"type": "object"},
        "args": {"city": "Lisbon"},
    }
    mapped = lg_interrupt_to_agui(LangGraphInterrupt(value=value, id="i1"))
    assert isinstance(mapped, Interrupt)
    assert (mapped.id, mapped.reason, mapped.tool_call_id, mapped.message) == (
        "i1",
        "tool_call",
        "c1",
        "Approve?",
    )
    assert mapped.response_schema == {"type": "object"}
    assert mapped.metadata is not None
    assert mapped.metadata["langgraph"]["raw"] == value


async def test_TD_8_4_3_the_resume_override_is_called_with_the_open_interrupts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DD-012: upstream calls our override, and LangGraph honors the native resume map."""
    answers.clear()
    agent = LangGraphAGUIAgent(_graph("a", "b"))
    events = await _run(agent, _input("r1"))
    finished = events[-1]
    assert isinstance(finished, RunFinishedEvent)
    assert finished.outcome is not None
    ids = [i.id for i in finished.outcome.interrupts]  # type: ignore[union-attr]
    assert len(ids) == 2

    seen: list[tuple[list[str], list[str]]] = []
    original = LangGraphAGUIAgent._build_command_from_agui_resume

    def spy(self: Any, entries: list[ResumeEntry], **kwargs: Any) -> Command[Any]:
        seen.append(([e.interrupt_id for e in entries], [i.id for i in kwargs["open_interrupts"]]))
        return original(self, entries, **kwargs)

    monkeypatch.setattr(LangGraphAGUIAgent, "_build_command_from_agui_resume", spy)
    resume = [ResumeEntry(interrupt_id=i, status="resolved", payload=f"answer {i}") for i in ids]
    await _run(agent, _input("r2", resume))
    assert seen == [(ids, ids)]
    assert sorted(answers.values()) == sorted(f"answer {i}" for i in ids)


async def test_DD_012_upstream_keeps_per_run_state_and_messages_in_snapshots() -> None:
    """DD-012: why ``run()`` clones and why the snapshot override drops ``messages``."""

    def reply(state: MessagesState) -> dict[str, Any]:
        return {"messages": [AIMessage(content="hi", id="ai-1")]}

    builder = StateGraph(MessagesState)
    builder.add_node("reply", reply)
    builder.add_edge(START, "reply")
    builder.add_edge("reply", END)
    upstream = LangGraphAgent(
        name="a",
        graph=builder.compile(checkpointer=InMemorySaver()),
        emit_interrupt_outcome=True,
        emit_raw_events=False,
    )
    during: list[bool] = []
    snapshots: list[Any] = []
    async for event in upstream.run(_input("r1")):
        during.append(upstream.active_run is not None)  # the run lives on the instance
        if isinstance(event, StateSnapshotEvent):
            snapshots.append(event.snapshot)
    assert all(during[1:-1])
    assert any("messages" in s for s in snapshots)


def test_TD_OQ_4_ag_ui_langgraph_imports_fastapi_unconditionally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TD DD-001, OQ-4: why the ``langgraph`` extra installs ``ag-ui-langgraph[fastapi]``."""
    real_import = builtins.__import__

    def no_fastapi(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "fastapi" or name.startswith("fastapi."):
            raise ModuleNotFoundError("No module named 'fastapi'", name="fastapi")
        return real_import(name, *args, **kwargs)

    for module in [
        m
        for m in sys.modules
        if m == "ag_ui_langgraph" or m.startswith(("ag_ui_langgraph.", "fastapi"))
    ]:
        monkeypatch.delitem(sys.modules, module)
    monkeypatch.setattr(builtins, "__import__", no_fastapi)
    with pytest.raises(ImportError, match="fastapi"):
        importlib.import_module("ag_ui_langgraph")
