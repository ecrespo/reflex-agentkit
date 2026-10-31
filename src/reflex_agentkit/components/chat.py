"""``agent_chat``: the full chat UI bound to an ``AgentState`` (API §10, REQ-023.1)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import reflex as rx

from reflex_agentkit.components.approval import InterruptRenderer, approval_dialog
from reflex_agentkit.components.composer import composer
from reflex_agentkit.components.messages import message_list
from reflex_agentkit.components.shared_state import shared_state_panel
from reflex_agentkit.components.status import run_status_bar
from reflex_agentkit.components.tools import ToolRenderer

__all__ = ["agent_chat"]


def agent_chat(
    state: type[Any],
    *,
    tool_renderers: Mapping[str, ToolRenderer] | None = None,
    interrupt_renderers: Mapping[str, InterruptRenderer] | None = None,
    show_shared_state: bool = False,
    placeholder: str = "Send a message…",
    **props: Any,
) -> rx.Component:
    """Messages, tool cards, the status bar, the composer and the approval dialog."""
    props.setdefault("width", "100%")
    props.setdefault("max_width", "48rem")
    props.setdefault("margin_x", "auto")
    props.setdefault("padding", "1em")
    parts: list[rx.Component] = [message_list(state, tool_renderers=tool_renderers)]
    if show_shared_state:
        parts.append(shared_state_panel(state))
    parts += [
        run_status_bar(state),
        composer(state, placeholder=placeholder),
        approval_dialog(state, interrupt_renderers=interrupt_renderers),
    ]
    return rx.vstack(*parts, spacing="4", **props)
