"""``run_status_bar`` (T-037, REQ-023.6)."""

from __future__ import annotations

from helpers.ui_state import UIState, render

from reflex_agentkit.components import run_status_bar


def test_REQ_023_6_status_step_cancel_and_error() -> None:
    """REQ-023.6: status and step; a cancel button while running; the error."""
    out = render(run_status_bar(UIState))
    assert "run_status" in out
    assert "current_step" in out
    assert "is_running" in out
    assert "cancel_run" in out
    assert "Cancel run" in out
    assert "error_rx_state_" in out
    assert "alert" in out
