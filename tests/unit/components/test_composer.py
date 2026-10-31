"""``composer`` (T-036, REQ-023.3, REQ-023.9)."""

from __future__ import annotations

from helpers.ui_state import UIState, render

from reflex_agentkit.components import composer


def test_REQ_023_3_enter_submits_and_send_is_gated_by_can_send() -> None:
    """REQ-023.3: Enter submits (Shift+Enter is a newline); disabled unless ``can_send``."""
    out = render(composer(UIState))
    assert "enterKeySubmit" in out or "enter_key_submit" in out
    assert "can_send" in out
    assert "send_message" in out
    assert 'type:"submit"' in out.replace(" ", "") or "submit" in out


def test_REQ_023_9_controls_have_labels() -> None:
    """REQ-023.9: the text area and the button have accessible labels."""
    out = render(composer(UIState, placeholder="Ask me"))
    assert "Message" in out  # aria-label of the text area
    assert "Send message" in out
    assert "Ask me" in out
