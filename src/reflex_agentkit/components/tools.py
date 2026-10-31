"""``tool_call_card``: one tool call with its status (API §10, REQ-019, REQ-023.4, DD-013)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import reflex as rx

from reflex_agentkit.core.models import ToolCall

__all__ = ["ToolRenderer", "tool_call_card"]

ToolRenderer = Callable[[rx.Var[ToolCall]], rx.Component]

_BADGE_COLORS: dict[str, str] = {
    "streaming": "gray",
    "pending_approval": "amber",
    "running": "blue",
    "done": "green",
    "rejected": "orange",
    "error": "red",
}


def _section(title: str, content: rx.Var[Any]) -> rx.Component:
    """A collapsible section whose content is shown as plain text, never markup (DD-015)."""
    return rx.el.details(
        rx.el.summary(title),
        rx.el.pre(content, style={"white_space": "pre-wrap", "word_break": "break-word"}),
    )


def default_tool_body(tool_call: rx.Var[ToolCall]) -> rx.Component:
    """Arguments and result as collapsible text sections (REQ-023.4)."""
    return rx.vstack(
        _section("Arguments", tool_call.args_text),
        rx.cond(tool_call.result, _section("Result", tool_call.result)),
        spacing="1",
        width="100%",
    )


def _status_badge(tool_call: rx.Var[ToolCall]) -> rx.Component:
    color = rx.match(
        tool_call.status,
        *((status, color) for status, color in _BADGE_COLORS.items()),
        "gray",
    )
    return rx.badge(tool_call.status, color_scheme=color, variant="soft")


def tool_call_card(
    state: type[Any],
    tool_call: rx.Var[ToolCall],
    *,
    body: ToolRenderer | None = None,
    renderers: Mapping[str, ToolRenderer] | None = None,
    **props: Any,
) -> rx.Component:
    """A card with the tool name, a status badge and a body (API §10).

    Args:
        state: The ``AgentState`` subclass (kept for a uniform signature).
        tool_call: The tool call var, usually from ``rx.foreach``.
        body: Replaces the default body for every call rendered by this card.
        renderers: Body renderers by tool name, resolved at compile time with
            ``rx.match`` (DD-013); other names use the default body.
        props: Standard Reflex props for the root element.
    """
    del state
    if body is not None:
        content = body(tool_call)
    elif renderers:
        content = rx.match(
            tool_call.name,
            *((name, render(tool_call)) for name, render in renderers.items()),
            default_tool_body(tool_call),
        )
    else:
        content = default_tool_body(tool_call)
    props.setdefault("width", "100%")
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.icon("wrench", size=14, aria_hidden="true"),
                rx.text(tool_call.name, weight="medium", size="2"),
                _status_badge(tool_call),
                align="center",
                spacing="2",
            ),
            content,
            spacing="2",
            width="100%",
        ),
        **props,
    )
