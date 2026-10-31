"""Agentic chat: a streaming conversation with an agent that can call a backend tool.

The agent answers in Markdown and may call ``current_time``. The tool call appears as a
card with its arguments and result; the reply streams token by token. "New conversation"
starts a fresh thread, and the status bar can stop a run.
"""

from __future__ import annotations

import datetime as dt
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import reflex as rx
from examples_shared.models import pydantic_ai_model
from pydantic_ai import Agent

from pydantic_ai_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

INSTRUCTIONS = """\
You are a friendly assistant in a demo app. Keep answers short and use Markdown when it
helps (lists, bold, code). When the user asks about the time anywhere, call the
`current_time` tool with an IANA time zone such as "Europe/Lisbon".
"""

chat_agent = Agent(pydantic_ai_model(), instructions=INSTRUCTIONS, name="agentic_chat")


@chat_agent.tool_plain
def current_time(timezone: str) -> str:
    """Return the current local time in an IANA time zone, such as "Asia/Tokyo"."""
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return f"Unknown time zone {timezone!r}."
    now = dt.datetime.now(zone)
    return f"It is {now:%H:%M} on {now:%A, %d %B %Y} in {timezone}."


class AgenticChatState(AgentState, rx.State):
    """The conversation with ``chat_agent``."""

    agent: ClassVar = PydanticAIAgent(chat_agent)


SUGGESTIONS = (
    "What time is it in Tokyo?",
    "Give me three tips for a first trip to Lisbon.",
    "Write a haiku about streaming tokens.",
)


def suggestion(text: str) -> rx.Component:
    """A button that sends a canned prompt."""
    return rx.button(
        text,
        variant="soft",
        size="1",
        on_click=AgenticChatState.send_message(text),
        disabled=~AgenticChatState.can_send,
    )


def page() -> rx.Component:
    return demo_page(
        "Agentic chat",
        "A streaming chat. Ask for the time somewhere to see a tool call.",
        rx.hstack(
            *[suggestion(text) for text in SUGGESTIONS],
            rx.spacer(),
            rx.button(
                "New conversation",
                variant="outline",
                size="1",
                on_click=AgenticChatState.new_thread,
            ),
            wrap="wrap",
            width="100%",
        ),
        agent_chat(AgenticChatState, placeholder="Ask me anything…"),
    )
