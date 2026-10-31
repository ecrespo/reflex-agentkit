"""Client protocols and validated event decoding (T-019, API §7.1-7.2)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest
from ag_ui.core import BaseEvent, RunAgentInput, RunStartedEvent, TextMessageContentEvent

from reflex_agentkit.core.clients.base import AgentClient, AgentSource, AGUIAgent, validate_event


class _Agent:
    async def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        yield RunStartedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id)


class _Client:
    async def stream(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        yield RunStartedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id)

    async def aclose(self) -> None:
        return None


def test_REQ_021_1_protocols_are_runtime_checkable() -> None:
    """REQ-021.1: structural checks for agents and clients."""
    assert isinstance(_Agent(), AGUIAgent)
    assert not isinstance(_Agent(), AgentClient)
    assert isinstance(_Client(), AgentClient)
    assert not isinstance(object(), AGUIAgent)
    source: AgentSource = _Client()
    assert source is not None


def test_REQ_012_3_valid_wire_events_are_decoded() -> None:
    """API §7.2: a camelCase dict becomes a validated event."""
    event = validate_event({"type": "RUN_STARTED", "threadId": "t", "runId": "r"})
    assert event == RunStartedEvent(thread_id="t", run_id="r")


def test_REQ_012_3_event_objects_are_revalidated() -> None:
    """API §7.2: objects built without validation are checked too."""
    good = TextMessageContentEvent(message_id="m", delta="hi")
    assert validate_event(good) == good
    bad = TextMessageContentEvent.model_construct(message_id="m", delta="")
    assert validate_event(bad) is None


def test_REQ_012_3_invalid_events_are_skipped_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-012.3: skip, and warn with the event type."""
    with caplog.at_level(logging.DEBUG, logger="reflex_agentkit"):
        assert validate_event({"type": "TEXT_MESSAGE_CONTENT", "messageId": "m"}) is None
    [record] = caplog.records
    assert record.levelno == logging.WARNING
    assert "TEXT_MESSAGE_CONTENT" in record.getMessage()


def test_REQ_012_2_unknown_events_are_skipped_at_debug(caplog: pytest.LogCaptureFixture) -> None:
    """REQ-012.2: unknown or removed types are skipped with a debug record."""
    with caplog.at_level(logging.DEBUG, logger="reflex_agentkit"):
        assert validate_event({"type": "THINKING_START"}) is None
    [record] = caplog.records
    assert record.levelno == logging.DEBUG


def test_REQ_012_3_non_objects_are_skipped(caplog: pytest.LogCaptureFixture) -> None:
    """REQ-012.3: anything that is not an event object is skipped with a warning."""
    with caplog.at_level(logging.DEBUG, logger="reflex_agentkit"):
        assert validate_event([1, 2]) is None
    assert caplog.records[0].levelno == logging.WARNING
