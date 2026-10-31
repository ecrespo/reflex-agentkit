"""The page frame shared by every demo."""

from __future__ import annotations

import reflex as rx

DEMOS: list[tuple[str, str, str]] = [
    ("/agentic-chat", "Agentic chat", "Streaming chat with a backend tool."),
    ("/backend-tools", "Backend tool rendering", "A custom card for a server-side tool."),
    ("/human-in-the-loop", "Human in the loop", "Approve, edit or reject a tool call."),
    ("/shared-state", "Shared state", "A recipe the agent and the user edit together."),
    ("/generative-ui", "Tool-based generative UI", "A chart drawn by a client tool."),
]


def demo_page(title: str, description: str, *children: rx.Component) -> rx.Component:
    """A heading, a back link and the demo's content."""
    return rx.container(
        rx.vstack(
            rx.link("← All demos", href="/"),
            rx.heading(title, size="7"),
            rx.text(description, color_scheme="gray"),
            *children,
            spacing="4",
            width="100%",
        ),
        size="4",
        padding_y="2em",
    )


def index() -> rx.Component:
    """The list of demos."""
    return rx.container(
        rx.vstack(
            rx.heading("reflex-agentkit Dojo · PydanticAI", size="8"),
            *[
                rx.card(rx.link(rx.heading(name, size="4"), href=route), rx.text(text))
                for route, name, text in DEMOS
            ],
            spacing="4",
        ),
        padding_y="2em",
    )
