"""LangGraph end to end through ``AgentState`` (T-044, REQ-034.2-3, REQ-014, REQ-015.3).

A scripted graph (``StateGraph`` + ``InMemorySaver`` + a fake chat model) runs through
``LangGraphAGUIAgent`` → ``InProcessAGUIClient`` → the driver and reducer, and resumes
through ``RunAgentInput.resume``. Nothing touches the network.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
import reflex as rx
from helpers.fake_chat_model import ScriptedChatModel
from helpers.reflex_harness import ReflexHarness
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from reflex_agentkit import AgentState
from reflex_agentkit.adapters.langgraph import (
    ApprovalDecision,
    LangGraphAGUIAgent,
    request_tool_approval,
)
from reflex_agentkit.core.models import RunStatus, ToolCallStatus

decisions: list[ApprovalDecision] = []
answers: dict[str, Any] = {}


@pytest.fixture(autouse=True)
def _reset() -> None:
    decisions.clear()
    answers.clear()


# --- an approval graph: the model asks for book_hotel, the tools node asks the user ---


def _approval_graph() -> LangGraphAGUIAgent:
    model = ScriptedChatModel(
        script=[
            AIMessage(
                content="Let me book that.",
                id="ai-1",
                tool_calls=[{"id": "c1", "name": "book_hotel", "args": {"city": "Lisbon"}}],
            ),
            AIMessage(content="All set.", id="ai-2"),
        ]
    )

    async def call_model(state: MessagesState) -> dict[str, Any]:
        return {"messages": [await model.ainvoke(state["messages"])]}

    def tools(state: MessagesState) -> dict[str, Any]:
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        call = last.tool_calls[0]
        decision = request_tool_approval(str(call["id"]), call["name"], call["args"])
        decisions.append(decision)
        if decision.approved:
            content = f"Booked {decision.args['city']}"
        else:
            content = f"Not booked: {decision.reason}"
        return {"messages": [ToolMessage(content=content, tool_call_id=call["id"], id="tm-1")]}

    def route(state: MessagesState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("tools", tools)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", route, ["tools", END])
    builder.add_edge("tools", "model")
    return LangGraphAGUIAgent(builder.compile(checkpointer=InMemorySaver()))


class HotelGraphState(AgentState, rx.State):
    agent: ClassVar = _approval_graph()


# --- a generic-interrupt graph: two parallel nodes each ask a question ---


def _question(node: str) -> Any:
    def ask(state: MessagesState) -> dict[str, Any]:
        answers[node] = interrupt({"reason": "confirm", "message": f"{node}?", "node": node})
        return {}

    return ask


def _questions_graph(*nodes: str) -> LangGraphAGUIAgent:
    def reply(state: MessagesState) -> dict[str, Any]:
        return {"messages": [AIMessage(content=f"answers: {answers}", id="ai-q")]}

    builder = StateGraph(MessagesState)
    builder.add_node("reply", reply)
    for node in nodes:
        builder.add_node(node, _question(node))
        builder.add_edge(START, node)
    builder.add_edge(list(nodes), "reply")
    builder.add_edge("reply", END)
    return LangGraphAGUIAgent(builder.compile(checkpointer=InMemorySaver()))


class OneQuestionState(AgentState, rx.State):
    agent: ClassVar = _questions_graph("dates")


class TwoQuestionsState(AgentState, rx.State):
    agent: ClassVar = _questions_graph("dates", "budget")


async def _pause_for_approval(rx_: ReflexHarness, token: str) -> HotelGraphState:
    await rx_.call(token, HotelGraphState, "send_message", text="book a hotel in Lisbon")
    state = await rx_.state(token, HotelGraphState)
    assert state.run_status == RunStatus.AWAITING_INPUT, state.error
    [call] = state.pending_approvals
    assert (call.id, call.name, call.args) == ("c1", "book_hotel", {"city": "Lisbon"})
    assert decisions == []
    return state


async def test_REQ_034_3_approval_with_edits_reaches_the_tool(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-034.3: the helper returns the decision, edited args included."""
    await _pause_for_approval(reflex_harness, "edit")
    await reflex_harness.call(
        "edit", HotelGraphState, "approve_tool", call_id="c1", edited_args={"city": "Porto"}
    )
    state = await reflex_harness.state("edit", HotelGraphState)
    assert state.run_status == RunStatus.IDLE, state.error
    assert decisions == [ApprovalDecision(approved=True, args={"city": "Porto"})]
    call = next(c for c in state.tool_calls if c.id == "c1")
    assert call.status == ToolCallStatus.DONE
    assert call.result == "Booked Porto"
    assert state.messages[-1].content == "All set."


async def test_REQ_034_3_rejection_reaches_the_tool(reflex_harness: ReflexHarness) -> None:
    """REQ-034.3, REQ-013.4: the call stays rejected after the graph's tool message."""
    await _pause_for_approval(reflex_harness, "reject")
    await reflex_harness.call(
        "reject", HotelGraphState, "reject_tool", call_id="c1", reason="too pricey"
    )
    state = await reflex_harness.state("reject", HotelGraphState)
    assert state.run_status == RunStatus.IDLE, state.error
    assert decisions == [
        ApprovalDecision(approved=False, args={"city": "Lisbon"}, reason="too pricey")
    ]
    call = next(c for c in state.tool_calls if c.id == "c1")
    assert call.status == ToolCallStatus.REJECTED


async def test_REQ_015_3_cancel_while_paused_resumes_as_a_cancelled_approval(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-015.2-3, DD-012: the next run tells the graph the approval was cancelled."""
    await _pause_for_approval(reflex_harness, "cancel")
    await reflex_harness.call("cancel", HotelGraphState, "cancel_run")
    state = await reflex_harness.state("cancel", HotelGraphState)
    assert state.run_status == RunStatus.CANCELLED
    assert next(c for c in state.tool_calls if c.id == "c1").status == ToolCallStatus.REJECTED

    await reflex_harness.call("cancel", HotelGraphState, "send_message", text="never mind")
    state = await reflex_harness.state("cancel", HotelGraphState)
    assert state.run_status == RunStatus.IDLE, state.error
    assert decisions == [
        ApprovalDecision(approved=False, args={"city": "Lisbon"}, reason="cancelled")
    ]


async def test_REQ_034_2_generic_interrupt_is_answered_with_respond_to_interrupt(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-034.2, REQ-014.1-2: ``interrupt(value)`` → ``pending_interrupt`` → resume."""
    await reflex_harness.call("ask", OneQuestionState, "send_message", text="plan a trip")
    state = await reflex_harness.state("ask", OneQuestionState)
    assert state.run_status == RunStatus.AWAITING_INPUT, state.error
    pending = state.pending_interrupt
    assert pending is not None
    assert (pending.reason, pending.message) == ("confirm", "dates?")
    assert pending.payload == {"reason": "confirm", "message": "dates?", "node": "dates"}

    await reflex_harness.call(
        "ask", OneQuestionState, "respond_to_interrupt", payload={"from": "May 1"}
    )
    state = await reflex_harness.state("ask", OneQuestionState)
    assert state.run_status == RunStatus.IDLE, state.error
    assert answers == {"dates": {"from": "May 1"}}
    assert state.pending_interrupt is None


async def test_REQ_014_3_two_simultaneous_interrupts_each_get_their_answer(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-014.3, DD-012: one at a time in the UI; the native resume map routes them."""
    session = "two"
    await reflex_harness.call(session, TwoQuestionsState, "send_message", text="plan a trip")
    state = await reflex_harness.state(session, TwoQuestionsState)
    assert state.run_status == RunStatus.AWAITING_INPUT, state.error
    for expected_position in (1, 2):
        pending = state.pending_interrupt
        assert pending is not None
        assert (pending.queue_position, pending.queue_size) == (expected_position, 2)
        assert isinstance(pending.payload, dict)
        node = pending.payload["node"]
        await reflex_harness.call(
            session, TwoQuestionsState, "respond_to_interrupt", payload=f"{node} answer"
        )
        state = await reflex_harness.state(session, TwoQuestionsState)
    assert state.run_status == RunStatus.IDLE, state.error
    assert answers == {"dates": "dates answer", "budget": "budget answer"}
