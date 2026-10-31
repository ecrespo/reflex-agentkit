"""Backend tool rendering: a server-side tool whose call is shown as a custom card.

``get_weather`` runs on the server, inside the agent. Instead of the default card body
(arguments and result as text), ``TOOL_RENDERERS`` gives it a weather card. The card
header with the tool name and status badge stays the same.
"""

from __future__ import annotations

import json
import random
from typing import Any, ClassVar

import reflex as rx
from examples_shared.models import pydantic_ai_model
from pydantic_ai import Agent

from pydantic_ai_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent
from reflex_agentkit.components import ToolRenderer

CONDITIONS = ("sunny", "cloudy", "light rain", "windy", "clear skies")

weather_agent = Agent(
    pydantic_ai_model(),
    instructions=(
        "You are a weather assistant. Call `get_weather` for every city the user names, "
        "then summarize the results in one or two sentences."
    ),
    name="backend_tools",
)


@weather_agent.tool_plain
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    rng = random.Random(city.lower())  # noqa: S311 - demo data, stable per city
    report: dict[str, Any] = {
        "city": city,
        "temperature_c": rng.randint(-5, 35),
        "conditions": rng.choice(CONDITIONS),
        "humidity_pct": rng.randint(20, 95),
        "wind_kmh": rng.randint(0, 60),
    }
    return json.dumps(report)


class BackendToolsState(AgentState, rx.State):
    """The conversation with ``weather_agent``."""

    agent: ClassVar = PydanticAIAgent(weather_agent)


def weather_card(tool_call: Any) -> rx.Component:
    """The body of a ``get_weather`` card: the city and the raw report while it runs."""
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
