"""``agent_chat`` composition and the accessibility pass (T-039, REQ-023.1, 023.8-9)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import reflex as rx
from helpers.ui_state import UIState, render
from reflex_components_core.base.bare import Bare  # type: ignore[import-untyped]
from reflex_components_core.core.foreach import Foreach  # type: ignore[import-untyped]
from reflex_components_core.core.match import Match  # type: ignore[import-untyped]

from reflex_agentkit.components import agent_chat

CONTROLS = {"Button", "IconButton", "TextArea", "TextFieldRoot", "Summary", "Select"}


def _walk(component: Any) -> Iterator[Any]:
    """Every component in the tree, including foreach bodies and match branches."""
    yield component
    children: list[Any] = list(getattr(component, "children", []))
    if isinstance(component, Foreach):
        children.append(component.render())
    if isinstance(component, Match):
        children += [case[-1] for case in component.match_cases]
        if component.default is not None:
            children.append(component.default)
    for child in children:
        if isinstance(child, rx.Component):
            yield from _walk(child)


def _has_text(component: Any) -> bool:
    return any(isinstance(c, Bare) and str(c.contents).strip(' "`{}') for c in _walk(component))


def _label(component: Any) -> str:
    props = component.render().get("props", [])
    return next((p for p in props if p.lstrip('"').startswith("aria-label")), "")


def test_REQ_023_1_agent_chat_renders_every_part_with_no_arguments() -> None:
    """REQ-023.1: messages, composer, tool cards, approval dialog and status bar."""
    out = render(agent_chat(UIState))
    for marker in ('role:"log"', "Send message", "Dialog.Root", "run_status", "tool_calls"):
        assert marker in out, marker
    assert "shared_state_stale" not in out
    assert "shared_state_stale" in render(agent_chat(UIState, show_shared_state=True))


def test_REQ_023_8_agent_chat_accepts_style_props() -> None:
    """REQ-023.8: standard Reflex style props reach the root."""
    out = str(agent_chat(UIState, max_width="60rem", id="chat"))
    assert "60rem" in out
    assert 'id:"chat"' in out


def test_REQ_023_9_every_control_has_an_accessible_label() -> None:
    """REQ-023.9: every button and input has an aria-label or visible text."""
    tree = list(_walk(agent_chat(UIState, show_shared_state=True)))
    controls = [c for c in tree if type(c).__name__ in CONTROLS]
    kinds = {type(c).__name__ for c in controls}
    assert {"Button", "TextArea", "Summary"} <= kinds
    unlabelled = [type(c).__name__ for c in controls if not (_label(c) or _has_text(c))]
    assert unlabelled == []
