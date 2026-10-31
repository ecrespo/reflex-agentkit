"""Agentic chat: a streaming conversation with a LangGraph agent that can call a tool.

The graph is the classic loop: the model answers, or asks for ``current_time``; LangGraph's
``ToolNode`` runs the tool and the model continues. The tool call shows as a card and the
reply streams token by token. "New conversation" starts a fresh thread.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import reflex as rx
from examples_shared.models import langgraph_model
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import tool
from langgraph.graph.state import CompiledStateGraph

from langgraph_dojo.graphs import chat_graph
from langgraph_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent

INSTRUCTIONS = """\
You are a friendly assistant in a demo app. Keep answers short and use Markdown when it
helps. When the user asks about the time anywhere, call `current_time` with an IANA time
zone such as "Europe/Lisbon".
"""


@tool
def current_time(timezone: str) -> str:
    """Return the current local time in an IANA time zone, such as "Asia/Tokyo"."""
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return f"Unknown time zone {timezone!r}."
    now = dt.datetime.now(zone)
    return f"It is {now:%H:%M} on {now:%A, %d %B %Y} in {timezone}."


def build_graph(model: BaseChatModel) -> CompiledStateGraph[Any, Any, Any, Any]:
    return chat_graph(model, [current_time], INSTRUCTIONS)


class AgenticChatState(AgentState, rx.State):
    """The conversation with the agentic-chat graph."""

    agent: ClassVar = LangGraphAGUIAgent(build_graph(langgraph_model()), name="agentic_chat")


STATE = AgenticChatState

SUGGESTIONS = (
    "What time is it in Tokyo?",
    "Give me three tips for a first trip to Lisbon.",
    "Write a haiku about graphs.",
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
        "A streaming chat on a LangGraph graph. Ask for the time somewhere.",
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
