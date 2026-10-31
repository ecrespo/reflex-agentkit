"""``tool_call_card`` (T-037, REQ-019, REQ-023.4, DD-013)."""

from __future__ import annotations

from typing import Any

import reflex as rx
from helpers.ui_state import UIState, render

from reflex_agentkit.components import tool_call_card


def _card(**kwargs: Any) -> str:
    return render(rx.foreach(UIState.tool_calls, lambda tc: tool_call_card(UIState, tc, **kwargs)))


def test_REQ_023_4_header_badge_and_collapsible_sections() -> None:
    """REQ-023.4: name, status badge, collapsible args and result."""
    out = _card()
    assert '["name"]' in out
    assert '["status"]' in out
    assert "details" in out
    assert "Arguments" in out
    assert "Result" in out
    assert '["args_text"]' in out


def test_REQ_019_2_default_body_without_renderers() -> None:
    """REQ-019.2, DD-013: no renderers → the default body and no match."""
    out = _card()
    assert "CUSTOM-BODY" not in out


def test_REQ_019_1_renderer_replaces_the_body_and_keeps_the_header() -> None:
    """REQ-019.1, DD-013: the renderer for a name replaces the body; the header stays."""
    renderers = {"show_chart": lambda tc: rx.text("CUSTOM-BODY")}
    out = render(
        rx.foreach(
            UIState.tool_calls,
            lambda tc: tool_call_card(UIState, tc, renderers=renderers),
        )
    )
    assert "CUSTOM-BODY" in out
    assert '"show_chart"' in out
    assert '["status"]' in out
    assert "Arguments" in out  # default body is still the fallback


def test_REQ_019_1_body_override() -> None:
    """API §10: ``body=`` replaces the default body for this card."""
    out = _card(body=lambda tc: rx.text("ONLY-BODY"))
    assert "ONLY-BODY" in out
    assert "Arguments" not in out
