"""``run_status_bar`` (API §10, REQ-023.6)."""

from __future__ import annotations

from typing import Any

import reflex as rx

__all__ = ["run_status_bar"]


def run_status_bar(state: type[Any], **props: Any) -> rx.Component:
    """The run status and step, a cancel button while running, and the error."""
    props.setdefault("width", "100%")
    return rx.vstack(
        rx.hstack(
            rx.badge(state.run_status, variant="soft", aria_label="Run status"),
            rx.cond(state.is_running, rx.spinner(size="1", aria_label="Running")),
            rx.cond(state.current_step != "", rx.text(state.current_step, size="1")),
            rx.spacer(),
            rx.cond(
                state.is_running,
                rx.button(
                    "Cancel",
                    on_click=state.cancel_run,
                    variant="soft",
                    color_scheme="red",
                    size="1",
                    aria_label="Cancel run",
                ),
            ),
            align="center",
            width="100%",
        ),
        rx.cond(
            state.error != "",
            rx.callout(state.error, icon="triangle_alert", color_scheme="red", role="alert"),
        ),
        spacing="2",
        **props,
    )
