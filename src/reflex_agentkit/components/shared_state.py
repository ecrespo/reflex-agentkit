"""``shared_state_panel`` (API §10, REQ-023.7)."""

from __future__ import annotations

from typing import Any

import reflex as rx

__all__ = ["shared_state_panel"]


def shared_state_panel(state: type[Any], **props: Any) -> rx.Component:
    """The shared state as JSON, with a marker while it is stale."""
    props.setdefault("width", "100%")
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text("Shared state", weight="medium", size="2"),
                rx.cond(
                    state.shared_state_stale,
                    rx.badge("stale", color_scheme="amber", aria_label="Shared state is stale"),
                ),
                align="center",
            ),
            rx.el.pre(
                state.shared_state.to_string(),
                style={"white_space": "pre-wrap", "word_break": "break-word"},
            ),
            spacing="2",
        ),
        **props,
    )
