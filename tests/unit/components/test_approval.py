"""``approval_dialog`` (T-038, REQ-023.5, REQ-014.3)."""

from __future__ import annotations

import reflex as rx
from helpers.ui_state import UIState, render

from reflex_agentkit.components import approval_dialog


def test_REQ_023_5_opens_on_approvals_or_interrupts() -> None:
    """REQ-023.5: open while an approval is pending or a generic interrupt is set."""
    out = render(approval_dialog(UIState))
    assert "pending_approvals" in out
    assert "pending_interrupt" in out


def test_REQ_023_5_approval_actions() -> None:
    """REQ-023.5: approve, approve with edited args, reject with an optional reason."""
    out = render(approval_dialog(UIState))
    for text in ("approve_tool", "reject_tool", "Approve", "Reject", "Edited arguments", "Reason"):
        assert text in out


def test_REQ_014_3_default_interrupt_form_and_queue_position() -> None:
    """REQ-014.3, REQ-023.5: a JSON payload editor and the queue position."""
    out = render(approval_dialog(UIState))
    assert "respond_to_interrupt" in out
    assert "queue_position" in out
    assert "Response" in out


def test_REQ_023_5_interrupt_renderer_by_reason() -> None:
    """API §10.2: a renderer for a reason replaces the default form."""
    renderers = {"pick_seat": lambda interrupt, state: rx.text("SEAT-PICKER")}
    out = render(approval_dialog(UIState, interrupt_renderers=renderers))
    assert "SEAT-PICKER" in out
    assert '"pick_seat"' in out
