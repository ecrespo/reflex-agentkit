"""``message_list`` (T-036, REQ-023.2, DD-015)."""

from __future__ import annotations

from helpers.ui_state import UIState, render

from reflex_agentkit.components import message_list


def test_REQ_023_2_messages_render_in_order_with_a_streaming_indicator() -> None:
    """REQ-023.2: one item per message, roles distinguished, a streaming indicator."""
    out = render(message_list(UIState))
    assert "messages_rx_state_" in out
    assert "Streaming" in out  # aria-label of the indicator
    assert ".streaming" in out
    assert '"user"' in out
    assert '"assistant"' in out
    assert '"tool"' in out


def test_DD_015_raw_html_not_rendered() -> None:
    """DD-015: markdown has no raw-HTML plugin, so ``<img onerror>`` stays text."""
    out = render(message_list(UIState))
    assert "rehypeRaw" not in out
    assert "rehype-raw" not in out


def test_REQ_019_tool_cards_follow_their_assistant_message() -> None:
    """REQ-023.1: tool calls render as cards under the message that issued them."""
    out = render(message_list(UIState))
    assert "tool_calls_rx_state_" in out
    assert "parent_message_id" in out


def test_REQ_023_8_props_reach_the_root() -> None:
    """REQ-023.8: standard props go on the root element."""
    assert "my-list" in render(message_list(UIState, class_name="my-list"))
