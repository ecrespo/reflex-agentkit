"""Tool-based generative UI: the graph draws a chart by calling a client tool.

``show_chart`` is a client tool. AG-UI sends its definition with each run, and
ag-ui-langgraph puts it in the graph's ``tools`` state key; the model binds it. When the
model calls it, the graph ends, the handler runs on the Reflex server, and a follow-up
run gives the model the result. The chart is the tool renderer, drawn from the call's
arguments.
"""

from __future__ import annotations

from typing import Any, ClassVar

import reflex as rx
from examples_shared.models import langgraph_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph

from langgraph_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat, client_tool
from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent
from reflex_agentkit.components import ToolRenderer

INSTRUCTIONS = """\
You are a data assistant. When the user wants to see numbers, call `show_chart` with a
short title, the labels and one value per label between 0 and 100. After the chart is
shown, explain it in one sentence.
"""


class ChartGraphState(MessagesState, total=False):
    """The conversation plus the client tools that AG-UI sends with each run."""

    tools: list[dict[str, Any]]


def as_function(tool: dict[str, Any]) -> dict[str, Any]:
    """An AG-UI tool definition in the OpenAI function format ``bind_tools`` accepts."""
    keys = ("name", "description", "parameters")
    return {"type": "function", "function": {k: tool[k] for k in keys if k in tool}}


def build_graph(model: BaseChatModel) -> CompiledStateGraph[Any, Any, Any, Any]:
    async def chat(state: ChartGraphState) -> dict[str, Any]:
        bound = model.bind_tools([as_function(t) for t in state.get("tools", [])])
        reply = await bound.ainvoke([SystemMessage(content=INSTRUCTIONS), *state["messages"]])
        return {"messages": [reply]}

    builder = StateGraph(ChartGraphState)
    builder.add_node("chat", chat)
    builder.add_edge(START, "chat")
    builder.add_edge("chat", END)  # a client-tool call ends the run; the app answers it
    return builder.compile(checkpointer=InMemorySaver())


@client_tool
def show_chart(title: str, labels: list[str], values: list[float]) -> str:
    """Show a bar chart in the chat. Values are percentages between 0 and 100."""
    if len(labels) != len(values):
        return "Not shown: labels and values must have the same length."
    return f"Chart {title!r} shown with {len(values)} bars."


class GenerativeUIState(AgentState, rx.State):
    """The conversation with the chart graph; ``show_chart`` runs here."""

    agent: ClassVar = LangGraphAGUIAgent(build_graph(langgraph_model()), name="charts")
    client_tools: ClassVar = (show_chart,)


STATE = GenerativeUIState


def bar(label: Any, value: Any) -> rx.Component:
    """One labelled bar."""
    return rx.hstack(
        rx.text(label, width="7em", size="2", trim="both"),
        rx.progress(value=value.to(int), max=100, width="100%"),
        rx.text(value.to_string(), size="1", color_scheme="gray"),
        align="center",
        width="100%",
    )


def chart_card(tool_call: Any) -> rx.Component:
    """The body of a ``show_chart`` card: the chart itself."""
    args = tool_call.args.to(dict)
    labels = args["labels"].to(list[str])
    values = args["values"].to(list[float])
    return rx.vstack(
        rx.heading(args["title"].to(str), size="4"),
        rx.foreach(labels, lambda label, i: bar(label, values[i])),
        spacing="2",
        width="100%",
    )


TOOL_RENDERERS: dict[str, ToolRenderer] = {"show_chart": chart_card}


def page() -> rx.Component:
    return demo_page(
        "Tool-based generative UI",
        "Ask for a chart: the graph calls a client tool and the chat draws it.",
        agent_chat(
            GenerativeUIState,
            tool_renderers=TOOL_RENDERERS,
            placeholder="Chart my screen time: Mon 40, Tue 65, Wed 30",
        ),
    )
