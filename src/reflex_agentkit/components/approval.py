"""``approval_dialog``: tool approvals and generic interrupts (API §10, REQ-023.5)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import reflex as rx

from reflex_agentkit.core.models import PendingInterrupt, ToolCall

__all__ = ["InterruptRenderer", "approval_dialog"]

InterruptRenderer = Callable[[rx.Var[PendingInterrupt], type[Any]], rx.Component]


def _approval(state: type[Any], call: rx.Var[ToolCall]) -> rx.Component:
    """Approve, approve with edited arguments, or reject one pending call."""
    return rx.vstack(
        rx.dialog.title(rx.text("Approve ", call.name, "?")),
        rx.el.pre(call.args_text, style={"white_space": "pre-wrap"}),
        rx.hstack(
            rx.button(
                "Approve",
                on_click=state.approve_tool(call.id),
                aria_label="Approve tool call",
            ),
            width="100%",
        ),
        rx.el.details(
            rx.el.summary("Edit arguments"),
            rx.form(
                rx.vstack(
                    rx.text_area(
                        name="edited_args",
                        default_value=call.args_text,
                        aria_label="Edited arguments",
                        width="100%",
                        rows="6",
                    ),
                    rx.button("Approve with edits", type="submit", aria_label="Approve with edits"),
                ),
                on_submit=lambda form: state.approve_tool(call.id, form.to(dict)["edited_args"]),
            ),
        ),
        rx.form(
            rx.hstack(
                rx.input(name="reason", placeholder="Reason (optional)", aria_label="Reason"),
                rx.button(
                    "Reject", type="submit", color_scheme="red", aria_label="Reject tool call"
                ),
                width="100%",
            ),
            on_submit=lambda form: state.reject_tool(call.id, form.to(dict)["reason"]),
            reset_on_submit=True,
        ),
        spacing="3",
        width="100%",
    )


def _default_interrupt(interrupt: rx.Var[PendingInterrupt], state: type[Any]) -> rx.Component:
    """The interrupt message and a JSON (or text) payload editor (REQ-023.5)."""
    return rx.form(
        rx.vstack(
            rx.text(interrupt.message),
            rx.text_area(
                name="payload",
                placeholder="Response (JSON or text)",
                aria_label="Response",
                width="100%",
                rows="4",
            ),
            rx.button("Send response", type="submit", aria_label="Send response"),
            spacing="2",
            width="100%",
        ),
        on_submit=lambda form: state.respond_to_interrupt(form.to(dict)["payload"]),
        reset_on_submit=True,
    )


def _interrupt(state: type[Any], renderers: Mapping[str, InterruptRenderer]) -> rx.Component:
    interrupt = state.pending_interrupt
    if renderers:
        body = rx.match(
            interrupt.reason,
            *((reason, render(interrupt, state)) for reason, render in renderers.items()),
            _default_interrupt(interrupt, state),
        )
    else:
        body = _default_interrupt(interrupt, state)
    return rx.vstack(
        rx.dialog.title(interrupt.reason),
        rx.text("Question ", interrupt.queue_position, " of ", interrupt.queue_size, size="1"),
        body,
        spacing="3",
        width="100%",
    )


def approval_dialog(
    state: type[Any],
    *,
    interrupt_renderers: Mapping[str, InterruptRenderer] | None = None,
    **props: Any,
) -> rx.Component:
    """A dialog open while an approval or a generic interrupt waits; approvals come first."""
    renderers = dict(interrupt_renderers or {})
    has_approval = state.pending_approvals.length() > 0
    open_ = has_approval | (state.pending_interrupt.is_not_none())
    return rx.dialog.root(
        rx.dialog.content(
            rx.cond(
                has_approval,
                _approval(state, state.pending_approvals[0]),
                rx.cond(state.pending_interrupt, _interrupt(state, renderers)),
            ),
            rx.dialog.description("The agent is waiting for your answer.", size="1"),
            **props,
        ),
        open=open_,
    )
