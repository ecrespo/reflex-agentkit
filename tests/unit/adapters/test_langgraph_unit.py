"""``LangGraphAGUIAgent`` construction, cloning and snapshots (T-042, REQ-034.1, REQ-034.4)."""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest
from ag_ui.core import BaseEvent, EventType, RunAgentInput, StateSnapshotEvent, UserMessage
from ag_ui_langgraph import LangGraphAgent
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent
from reflex_agentkit.core import AdapterNotInstalledError, AGUIAgent, ConfigurationError


class PlanState(MessagesState):
    plan: list[str]


def _reply(state: PlanState) -> dict[str, Any]:
    return {"messages": [AIMessage(content="done", id="ai-1")], "plan": ["pack", "fly"]}


def _graph(*, checkpointer: bool = True) -> CompiledStateGraph[Any, Any, Any, Any]:
    builder = StateGraph(PlanState)
    builder.add_node("reply", _reply)
    builder.add_edge(START, "reply")
    builder.add_edge("reply", END)
    return builder.compile(checkpointer=InMemorySaver() if checkpointer else None)


def _input(run_id: str = "r1") -> RunAgentInput:
    return RunAgentInput(
        thread_id="t1",
        run_id=run_id,
        messages=[UserMessage(id="u1", role="user", content="plan a trip")],
        tools=[],
        context=[],
        state={},
        forwarded_props={},
    )


async def _events(agent: LangGraphAGUIAgent, run_input: RunAgentInput) -> list[BaseEvent]:
    return [event async for event in agent.run(run_input)]


def test_REQ_034_1_wraps_the_official_integration_with_interrupt_outcomes() -> None:
    """REQ-034.1, DD-012: the upstream agent with structured interrupts and no RAW events."""
    agent = LangGraphAGUIAgent(_graph(), name="planner")
    assert isinstance(agent, LangGraphAgent)
    assert isinstance(agent, AGUIAgent)
    assert agent.name == "planner"
    assert agent.emit_interrupt_outcome is True
    assert agent.enable_legacy_on_interrupt_event is False
    assert agent.emit_raw_events is False


def test_REQ_034_4_a_graph_without_checkpointer_is_rejected() -> None:
    """REQ-034.4: no checkpointer means interrupts could never resume."""
    with pytest.raises(ConfigurationError, match="checkpointer"):
        LangGraphAGUIAgent(_graph(checkpointer=False))


def test_REQ_034_4_only_compiled_graphs_are_accepted() -> None:
    with pytest.raises(ConfigurationError, match="compiled"):
        LangGraphAGUIAgent(object())  # type: ignore[arg-type]


def test_REQ_034_1_clone_keeps_the_settings() -> None:
    """DD-012: ``clone()`` rebuilds through our own signature."""
    agent = LangGraphAGUIAgent(_graph(), name="planner", config={"recursion_limit": 5})
    copy = agent.clone()
    assert copy is not agent
    assert isinstance(copy, LangGraphAGUIAgent)
    assert (copy.name, copy.graph, copy.config) == ("planner", agent.graph, agent.config)
    assert copy.emit_interrupt_outcome is True
    assert copy.emit_raw_events is False


async def test_REQ_034_1_runs_on_a_fresh_clone_so_sessions_can_share_it() -> None:
    """DD-012: the shared instance never holds per-run state."""
    agent = LangGraphAGUIAgent(_graph())
    events = await _events(agent, _input())
    types = [e.type for e in events]
    assert types[0] == EventType.RUN_STARTED
    assert types[-1] == EventType.RUN_FINISHED
    assert agent.active_run is None
    assert agent.messages_in_process == {}


async def test_DD_012_state_snapshots_leave_out_messages_and_tools() -> None:
    """DD-012: the conversation is not duplicated into ``shared_state``."""
    events = await _events(LangGraphAGUIAgent(_graph()), _input())
    snapshots = [e.snapshot for e in events if isinstance(e, StateSnapshotEvent)]
    assert snapshots
    assert snapshots[-1] == {"plan": ["pack", "fly"]}
    assert all("messages" not in s and "tools" not in s for s in snapshots)


def test_REQ_021_6_repr_shows_only_the_name() -> None:
    """The config may hold credentials; ``repr`` never shows it."""
    agent = LangGraphAGUIAgent(_graph(), name="planner", config={"configurable": {"key": "S3"}})
    assert repr(agent) == "LangGraphAGUIAgent(name='planner')"


def test_REQ_031_3_importing_the_adapter_without_the_extra_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-031.3, API §7.7: the documented install hint."""
    monkeypatch.setitem(sys.modules, "ag_ui_langgraph", None)
    monkeypatch.delitem(sys.modules, "reflex_agentkit.adapters.langgraph", raising=False)
    with pytest.raises(AdapterNotInstalledError) as info:
        importlib.import_module("reflex_agentkit.adapters.langgraph")
    assert str(info.value) == (
        "reflex_agentkit.adapters.langgraph requires the 'langgraph' extra: "
        "pip install 'reflex-agentkit[langgraph]'"
    )
