"""Contract tests: the AG-UI protocol facts the core relies on (TD §8.4 item 1, DD-001).

If an ``ag-ui-protocol`` upgrade breaks one of these, the reducer and the run-input
builder must be revisited before the pin in DD-001 is raised.
"""

from __future__ import annotations

import typing

from ag_ui.core import (
    EventType,
    Interrupt,
    ResumeEntry,
    RunAgentInput,
    RunFinishedCancelledOutcome,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunFinishedOutcome,
    RunFinishedSuccessOutcome,
)
from pydantic import TypeAdapter

V1_EVENT_TYPES = {
    "TEXT_MESSAGE_START",
    "TEXT_MESSAGE_CONTENT",
    "TEXT_MESSAGE_END",
    "TEXT_MESSAGE_CHUNK",
    "TOOL_CALL_START",
    "TOOL_CALL_ARGS",
    "TOOL_CALL_END",
    "TOOL_CALL_CHUNK",
    "TOOL_CALL_RESULT",
    "STATE_SNAPSHOT",
    "STATE_DELTA",
    "MESSAGES_SNAPSHOT",
    "ACTIVITY_SNAPSHOT",
    "ACTIVITY_DELTA",
    "RAW",
    "CUSTOM",
    "RUN_STARTED",
    "RUN_FINISHED",
    "RUN_ERROR",
    "STEP_STARTED",
    "STEP_FINISHED",
    "REASONING_START",
    "REASONING_MESSAGE_START",
    "REASONING_MESSAGE_CONTENT",
    "REASONING_MESSAGE_END",
    "REASONING_MESSAGE_CHUNK",
    "REASONING_END",
    "REASONING_ENCRYPTED_VALUE",
    "SUBAGENT_STARTED",
    "SUBAGENT_FINISHED",
    "SUBAGENT_ERROR",
}


def test_DD_001_event_type_has_the_31_v1_values() -> None:
    """TD §8.4 (1): ``EventType`` has exactly the 31 AG-UI 1.0 values."""
    values = {member.value for member in EventType}
    assert values == V1_EVENT_TYPES
    assert len(values) == 31


def test_DD_001_event_type_has_no_thinking_values() -> None:
    """TD §8.4 (1): the deprecated ``THINKING_*`` events are gone from the enum."""
    assert not [m.value for m in EventType if m.value.startswith("THINKING")]


def test_DD_001_run_finished_outcome_discriminates_three_variants() -> None:
    """TD §8.4 (1): ``RunFinishedOutcome`` is discriminated by ``type``."""
    adapter: TypeAdapter[typing.Any] = TypeAdapter(RunFinishedOutcome)
    assert isinstance(adapter.validate_python({"type": "success"}), RunFinishedSuccessOutcome)
    assert isinstance(adapter.validate_python({"type": "cancelled"}), RunFinishedCancelledOutcome)
    interrupt = adapter.validate_python(
        {"type": "interrupt", "interrupts": [{"id": "i1", "reason": "tool_call"}]}
    )
    assert isinstance(interrupt, RunFinishedInterruptOutcome)
    assert interrupt.interrupts[0].id == "i1"


def test_DD_001_run_finished_event_carries_an_outcome() -> None:
    """TD §8.4 (1): ``RUN_FINISHED`` exposes ``outcome`` for interrupts (PRD D-03)."""
    assert "outcome" in RunFinishedEvent.model_fields


def test_DD_001_success_outcome_lists_pending_tool_call_ids() -> None:
    """TD §8.4 (2, A-18): the success outcome may list calls awaiting client results."""
    assert "pending_tool_call_ids" in RunFinishedSuccessOutcome.model_fields


def test_DD_001_interrupt_has_the_fields_we_use() -> None:
    """TD §8.4 (1): ``Interrupt`` fields read by the reducer and the approval UI."""
    assert {"id", "reason", "message", "tool_call_id", "response_schema", "metadata"} <= set(
        Interrupt.model_fields
    )


def test_DD_001_resume_entry_has_the_fields_we_use() -> None:
    """TD §8.4 (1): ``ResumeEntry`` fields written by the run-input builder."""
    assert {"interrupt_id", "status", "payload"} <= set(ResumeEntry.model_fields)


def test_DD_001_run_agent_input_accepts_resume() -> None:
    """TD §8.4 (1): ``RunAgentInput`` carries ``resume[]`` for interrupt answers."""
    assert "resume" in RunAgentInput.model_fields
