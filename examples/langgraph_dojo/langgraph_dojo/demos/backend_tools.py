"""Backend tool rendering: a graph tool whose call is shown as a custom card.

``get_weather`` runs in the graph's ``ToolNode``. ``TOOL_RENDERERS`` replaces the default
card body (arguments and result as text) with a weather card; the header with the tool
name and status badge stays.
"""

from __future__ import annotations

import json
import random
from typing import Any, ClassVar

import reflex as rx
from examples_shared.models import langgraph_model
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langgraph.graph.state import CompiledStateGraph

from langgraph_dojo.graphs import chat_graph
from langgraph_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent
from reflex_agentkit.components import ToolRenderer

INSTRUCTIONS = (
    "You are a weather assistant. Call `get_weather` for every city the user names, then "
    "summarize the results in one or two sentences."
)
CONDITIONS = ("sunny", "cloudy", "light rain", "windy", "clear skies")


@tool
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    rng = random.Random(city.lower())  # noqa: S311 - demo data, stable per city
    report = {
        "city": city,
        "temperature_c": rng.randint(-5, 35),
        "conditions": rng.choice(CONDITIONS),
        "humidity_pct": rng.randint(20, 95),
        "wind_kmh": rng.randint(0, 60),
    }
    return json.dumps(report)


def build_graph(model: BaseChatModel) -> CompiledStateGraph[Any, Any, Any, Any]:
    return chat_graph(model, [get_weather], INSTRUCTIONS)


class BackendToolsState(AgentState, rx.State):
    """The conversation with the weather graph."""

    agent: ClassVar = LangGraphAGUIAgent(build_graph(langgraph_model()), name="backend_tools")


STATE = BackendToolsState


def weather_card(tool_call: Any) -> rx.Component:
    """The body of a ``get_weather`` card: the city and the report."""
    city = tool_call.args.to(dict)["city"].to(str)
    return rx.vstack(
        rx.hstack(
            rx.icon("cloud-sun", size=28),
            rx.heading(rx.cond(city, city, "…"), size="5"),
            align="center",
        ),
        rx.cond(
            tool_call.result,
            rx.code_block(tool_call.result.to(str), language="json", width="100%"),
            rx.text("Checking the sky…", color_scheme="gray"),
        ),
        spacing="2",
        width="100%",
    )


TOOL_RENDERERS: dict[str, ToolRenderer] = {"get_weather": weather_card}


def page() -> rx.Component:
    return demo_page(
        "Backend tool rendering",
        "Ask for the weather in a few cities: each call gets a weather card.",
        agent_chat(
            BackendToolsState,
            tool_renderers=TOOL_RENDERERS,
            placeholder="What's the weather in Lisbon and Oslo?",
        ),
    )
