"""Human in the loop: the agent must ask before it books anything.

``book_trip`` is declared with ``requires_approval=True``. When the agent calls it, the
run pauses and the approval dialog opens: approve, edit the arguments, or reject with a
reason. The decision goes back to PydanticAI, which runs the tool with the (possibly
edited) arguments or tells the model it was rejected.
"""

from __future__ import annotations

from typing import ClassVar

import reflex as rx
from examples_shared.models import pydantic_ai_model
from pydantic_ai import Agent

from pydantic_ai_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

INSTRUCTIONS = """\
You are a travel agent. Plan trips with the user, then book them with `book_trip`.
Booking needs the user's approval: if they reject it, ask what to change. Mention the
final price after a successful booking.
"""

travel_agent = Agent(pydantic_ai_model(), instructions=INSTRUCTIONS, name="human_in_the_loop")

NIGHTLY_RATE_EUR = 120


@travel_agent.tool_plain(requires_approval=True)
def book_trip(destination: str, nights: int, travelers: int = 1) -> str:
    """Book a hotel stay. The user must approve it first."""
    nights = max(nights, 1)
    travelers = max(travelers, 1)
    price = nights * travelers * NIGHTLY_RATE_EUR
    return (
        f"Booked {nights} night(s) in {destination} for {travelers} traveler(s). "
        f"Total: {price} EUR."
    )


@travel_agent.tool_plain
def list_destinations() -> list[str]:
    """List the destinations this agency can book."""
    return ["Lisbon", "Kyoto", "Reykjavik", "Cape Town", "Buenos Aires"]


class HumanInTheLoopState(AgentState, rx.State):
    """The conversation with ``travel_agent``."""

    agent: ClassVar = PydanticAIAgent(travel_agent)


def pending_banner() -> rx.Component:
    """A hint shown while the run waits for a decision."""
    return rx.cond(
        HumanInTheLoopState.awaiting_input,
        rx.callout(
            "The agent is waiting for your decision in the dialog.",
            icon="hand",
            color_scheme="amber",
        ),
    )


def page() -> rx.Component:
    return demo_page(
        "Human in the loop",
        "Ask for a booking. Nothing is booked until you approve it.",
        pending_banner(),
        agent_chat(
            HumanInTheLoopState,
            placeholder="Book 3 nights in Kyoto for two people",
        ),
    )
