"""``composer``: the message input (API §10, REQ-023.3, REQ-023.9)."""

from __future__ import annotations

from typing import Any

import reflex as rx

__all__ = ["composer"]


def composer(
    state: type[Any], *, placeholder: str = "Send a message…", **props: Any
) -> rx.Component:
    """A text area and a send button; disabled unless ``state.can_send``.

    Enter submits and Shift+Enter inserts a newline (REQ-023.3).
    """
    props.setdefault("width", "100%")
    return rx.form(
        rx.hstack(
            rx.text_area(
                name="message",
                placeholder=placeholder,
                enter_key_submit=True,
                disabled=~state.can_send,
                aria_label="Message",
                width="100%",
                rows="2",
                resize="vertical",
            ),
            rx.button(
                rx.icon("send", size=16, aria_hidden="true"),
                type="submit",
                disabled=~state.can_send,
                aria_label="Send message",
            ),
            align="end",
            width="100%",
        ),
        on_submit=lambda form: state.send_message(form.to(dict)["message"]),
        reset_on_submit=True,
        **props,
    )
