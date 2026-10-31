"""``message_list``: the conversation in order (API §10, REQ-023.2, DD-015)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import reflex as rx

from reflex_agentkit.components.tools import ToolRenderer, tool_call_card
from reflex_agentkit.core.models import ChatMessage, ToolCall

__all__ = ["message_list"]


def _markdown(content: rx.Var[str]) -> rx.Component:
    # Raw HTML is on by default in Reflex 0.10.1; model output must stay text (DD-015).
    return rx.markdown(content, use_raw=False)


def _streaming_indicator(message: rx.Var[ChatMessage]) -> rx.Component:
    return rx.cond(
        message.streaming,
        rx.spinner(size="1", aria_label="Streaming"),
    )


def _tool_cards(
    state: type[Any], message: rx.Var[ChatMessage], renderers: Mapping[str, ToolRenderer]
) -> rx.Component:
    def card(tool_call: rx.Var[ToolCall]) -> rx.Component:
        return rx.cond(
            tool_call.parent_message_id == message.id,
            tool_call_card(state, tool_call, renderers=renderers),
        )

    return rx.foreach(state.tool_calls, card)


def _message(
    state: type[Any], message: rx.Var[ChatMessage], renderers: Mapping[str, ToolRenderer]
) -> rx.Component:
    return rx.match(
        message.role,
        (
            "user",
            rx.box(
                rx.text(message.content, white_space="pre-wrap"),
                align_self="flex-end",
                background_color=rx.color("accent", 3),
                padding="0.5em 0.75em",
                border_radius="0.75em",
                max_width="80%",
                aria_label="User message",
            ),
        ),
        (
            "assistant",
            rx.vstack(
                rx.cond(
                    message.reasoning,
                    rx.el.details(
                        rx.el.summary("Reasoning"),
                        rx.text(message.reasoning, size="1", color_scheme="gray"),
                    ),
                ),
                rx.cond(message.content, _markdown(message.content)),
                _streaming_indicator(message),
                _tool_cards(state, message, renderers),
                align_self="flex-start",
                width="100%",
                spacing="2",
                aria_label="Assistant message",
            ),
        ),
        (
            "tool",
            rx.el.details(
                rx.el.summary("Tool result"),
                rx.el.pre(message.content, style={"white_space": "pre-wrap"}),
                aria_label="Tool message",
            ),
        ),
        rx.fragment(),
    )


def message_list(
    state: type[Any], *, tool_renderers: Mapping[str, ToolRenderer] | None = None, **props: Any
) -> rx.Component:
    """User, assistant and tool messages in order, with tool calls under their message.

    Assistant text is rendered as markdown without raw HTML (DD-015); tool arguments and
    results are plain text.
    """
    renderers = dict(tool_renderers or {})
    props.setdefault("width", "100%")
    props.setdefault("spacing", "3")
    return rx.vstack(
        rx.foreach(state.messages, lambda m: _message(state, m, renderers)),
        role="log",
        aria_live="polite",
        **props,
    )
