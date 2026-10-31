from typing import ClassVar

import reflex as rx
from pydantic_ai import Agent

from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

travel_agent = Agent(
    "anthropic:claude-sonnet-5-5",
    instructions="You are a helpful travel assistant.",
)


@travel_agent.tool_plain
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It is sunny and 22 °C in {city}."


@travel_agent.tool_plain(requires_approval=True)
def book_hotel(city: str, nights: int) -> str:
    """Book a hotel room. Requires human approval."""
    return f"Booked {nights} nights in {city}."


class ChatState(AgentState, rx.State):
    agent: ClassVar = PydanticAIAgent(travel_agent)


def index() -> rx.Component:
    return agent_chat(ChatState)


app = rx.App()
app.add_page(index)
