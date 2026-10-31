"""Human in the loop: the graph asks the user questions and asks before it books.

Two LangGraph patterns, both through AG-UI standard interrupts:
- ``ask_user`` calls ``interrupt()``: the question appears in the dialog (with a custom
  form, ``INTERRUPT_RENDERERS``) and the answer becomes the tool result;
- ``book_trip`` calls ``request_tool_approval``: the call card waits for approve, edit or
  reject, and the tool runs with the approved (possibly edited) arguments.
"""

from __future__ import annotations

from typing import Any, ClassVar

import reflex as rx
from examples_shared.models import langgraph_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from langgraph_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent, request_tool_approval
from reflex_agentkit.components import InterruptRenderer

INSTRUCTIONS = """\
You are a travel agent. If you need a detail (dates, number of nights, travelers), call
`ask_user`. Then book with `book_trip`; the user must approve it. If they reject it, ask
what to change.
"""
NIGHTLY_RATE_EUR = 120


@tool
def ask_user(question: str) -> str:
    """Ask the user a question and wait for the answer."""
    return str(interrupt({"reason": "question", "message": question}))


@tool
def book_trip(destination: str, nights: int, travelers: int = 1) -> str:
    """Book a hotel stay. The user must approve it first."""
    price = max(nights, 1) * max(travelers, 1) * NIGHTLY_RATE_EUR
    return f"Booked {nights} night(s) in {destination} for {travelers}. Total: {price} EUR."


def act(state: MessagesState) -> dict[str, Any]:
    """Run the requested tools; ``book_trip`` only after the user approves it."""
    last = state["messages"][-1]
    if not isinstance(last, AIMessage):
        raise TypeError("expected the model's tool calls")
    results: list[ToolMessage] = []
    for call in last.tool_calls:
        call_id = str(call["id"])
        if call["name"] == "book_trip":
            decision = request_tool_approval(call_id, "book_trip", call["args"])
            if decision.approved:
                content = book_trip.invoke(decision.args)
            else:
                content = f"The user rejected the booking: {decision.reason or 'no reason'}."
        else:
            content = ask_user.invoke(call["args"])
        results.append(ToolMessage(content=content, tool_call_id=call_id))
    return {"messages": results}


def build_graph(model: BaseChatModel) -> CompiledStateGraph[Any, Any, Any, Any]:
    bound = model.bind_tools([ask_user, book_trip])

    async def chat(state: MessagesState) -> dict[str, Any]:
        reply = await bound.ainvoke([SystemMessage(content=INSTRUCTIONS), *state["messages"]])
        return {"messages": [reply]}

    def route(state: MessagesState) -> str:
        return "act" if getattr(state["messages"][-1], "tool_calls", None) else END

    builder = StateGraph(MessagesState)
    builder.add_node("chat", chat)
    builder.add_node("act", act)
    builder.add_edge(START, "chat")
    builder.add_conditional_edges("chat", route, ["act", END])
    builder.add_edge("act", "chat")
    return builder.compile(checkpointer=InMemorySaver())


class HumanInTheLoopState(AgentState, rx.State):
    """The conversation with the travel graph."""

    agent: ClassVar = LangGraphAGUIAgent(build_graph(langgraph_model()), name="travel")


STATE = HumanInTheLoopState


def question_form(pending: Any, state: Any) -> rx.Component:
    """A plain text answer for ``ask_user`` questions."""
    return rx.form(
        rx.vstack(
            rx.text(pending.message, weight="medium"),
            rx.input(name="answer", aria_label="Your answer", width="100%"),
            rx.button("Send answer", type="submit"),
            width="100%",
        ),
        on_submit=lambda form: state.respond_to_interrupt(form.to(dict)["answer"]),
        reset_on_submit=True,
    )


INTERRUPT_RENDERERS: dict[str, InterruptRenderer] = {"question": question_form}


def page() -> rx.Component:
    return demo_page(
        "Human in the loop",
        "Ask for a booking: the agent may ask you questions, and books only on approval.",
        agent_chat(
            HumanInTheLoopState,
            interrupt_renderers=INTERRUPT_RENDERERS,
            placeholder="Book a trip to Kyoto",
        ),
    )
