"""Tool-based generative UI: the agent draws a chart by calling a client tool.

``show_chart`` is a client tool: the agent sees it as a frontend tool, the call ends the
run, the handler runs on the Reflex server and a follow-up run continues. The handler
only confirms; the UI is the tool renderer, which draws the bars from the call's
arguments.
"""

from __future__ import annotations

from typing import Any, ClassVar

import reflex as rx
from examples_shared.models import pydantic_ai_model
from pydantic_ai import Agent

from pydantic_ai_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat, client_tool
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent
from reflex_agentkit.components import ToolRenderer

INSTRUCTIONS = """\
You are a data assistant. When the user wants to see numbers, call `show_chart` with a
short title, the labels and one value per label between 0 and 100. After the chart is
shown, explain it in one sentence.
"""

chart_agent = Agent(pydantic_ai_model(), instructions=INSTRUCTIONS, name="generative_ui")


@client_tool
def show_chart(title: str, labels: list[str], values: list[float]) -> str:
    """Show a bar chart in the chat. Values are percentages between 0 and 100."""
    if len(labels) != len(values):
        return "Not shown: labels and values must have the same length."
    return f"Chart {title!r} shown with {len(values)} bars."


class GenerativeUIState(AgentState, rx.State):
    """The conversation with ``chart_agent``; ``show_chart`` runs here."""

    agent: ClassVar = PydanticAIAgent(chart_agent)
    client_tools: ClassVar = (show_chart,)


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
        "Ask for a chart: the agent calls a client tool and the chat draws it.",
        agent_chat(
            GenerativeUIState,
            tool_renderers=TOOL_RENDERERS,
            placeholder="Chart my screen time: Mon 40, Tue 65, Wed 30",
        ),
    )
