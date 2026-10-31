"""``shared_state_panel`` (T-038, REQ-023.7)."""

from __future__ import annotations

from helpers.ui_state import UIState, render

from reflex_agentkit.components import shared_state_panel


def test_REQ_023_7_json_and_stale_marker() -> None:
    """REQ-023.7: the shared state as JSON, and a stale marker."""
    out = render(shared_state_panel(UIState))
    assert "JSON.stringify" in out
    assert "shared_state_stale" in out
    assert "stale" in out
