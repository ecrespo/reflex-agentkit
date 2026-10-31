"""Reducer: dispatch, lifecycle, steps, tolerated and unknown events (T-010)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from ag_ui.core import (
    BaseEvent,
    EventType,
    RawEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StepFinishedEvent,
    StepStartedEvent,
)
from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    Diagnostic,
    DiagnosticCode,
    MessageRole,
    ReducerConfig,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from reflex_agentkit.core.reducer import parse_event, reduce

CONFIG = ReducerConfig()


def _running() -> ConversationState:
    return begin_run(ConversationState.initial(CONFIG), user_text="hi", config=CONFIG)


def _started() -> ConversationState:
    conv = _running()
    return reduce(conv, RunStartedEvent(thread_id=conv.thread_id, run_id=conv.run_id))


def _codes(conv: ConversationState) -> list[DiagnosticCode]:
    return [d.code for d in conv.diagnostics]


# --- parse_event --------------------------------------------------------------------------


def test_REQ_012_3_parse_event_returns_a_validated_event() -> None:
    """REQ-012.3: a valid wire event is parsed into its ``ag_ui.core`` model."""
    event = parse_event({"type": "RUN_STARTED", "threadId": "t", "runId": "r"})
    assert isinstance(event, RunStartedEvent)
    assert event.run_id == "r"


@pytest.mark.parametrize(
    ("raw", "event_type"),
    [
        ({"type": "RUN_STARTED", "threadId": "t"}, "RUN_STARTED"),
        ({"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": 3}, "TEXT_MESSAGE_CONTENT"),
        ({"no_type": True}, None),
        (["not", "an", "object"], None),
    ],
    ids=["missing-field", "wrong-type", "no-type", "not-an-object"],
)
def test_REQ_012_3_parse_event_turns_invalid_events_into_warnings(
    raw: Any, event_type: str | None
) -> None:
    """REQ-012.3: validation failures become a warning that names the event type."""
    diag = parse_event(raw)
    assert isinstance(diag, Diagnostic)
    assert diag.level == "warning"
    assert diag.code is DiagnosticCode.INVALID_EVENT
    assert diag.event_type == event_type
    if event_type:
        assert event_type in diag.message


@pytest.mark.parametrize("event_type", ["THINKING_START", "THINKING_TEXT_MESSAGE_CONTENT", "NEW"])
def test_REQ_012_2_parse_event_turns_unknown_types_into_debug_diagnostics(
    event_type: str,
) -> None:
    """REQ-012.2: unknown and deprecated (``THINKING_*``) types are skipped at debug level."""
    diag = parse_event({"type": event_type})
    assert isinstance(diag, Diagnostic)
    assert diag.level == "debug"
    assert diag.code is DiagnosticCode.UNKNOWN_EVENT_TYPE
    assert diag.event_type == event_type


# --- lifecycle ----------------------------------------------------------------------------


def test_REQ_010_1_run_started_records_the_active_run_id() -> None:
    """REQ-010.1: ``RUN_STARTED`` records its ``runId`` as the active run."""
    conv = _running()
    after = reduce(conv, RunStartedEvent(thread_id=conv.thread_id, run_id=conv.run_id))
    assert after.run_id == conv.run_id
    assert after.diagnostics == ()


def test_REQ_010_1_late_run_started_of_an_earlier_run_keeps_the_active_run() -> None:
    """REQ-010.1, TD Flow A.7: an earlier run of the turn never becomes active again."""
    first = _running()
    follow_up = begin_run(first, resume=True, config=CONFIG)
    after = reduce(follow_up, RunStartedEvent(thread_id=first.thread_id, run_id=first.run_id))
    assert after == follow_up
    assert after.run_id == follow_up.run_id


def test_REQ_010_2_run_started_for_another_run_is_discarded() -> None:
    """REQ-010.2: a ``RUN_STARTED`` of a run outside this turn is skipped with a warning."""
    conv = _running()
    after = reduce(conv, RunStartedEvent(thread_id=conv.thread_id, run_id="old"))
    assert after.run_id == conv.run_id
    assert _codes(after) == [DiagnosticCode.STALE_RUN_EVENT]
    assert after.diagnostics[0].level == "warning"


def test_REQ_010_2_run_finished_for_another_run_is_discarded() -> None:
    """REQ-010.2: a ``RUN_FINISHED`` of a stale run does not end the active one."""
    conv = _started()
    after = reduce(conv, RunFinishedEvent(thread_id=conv.thread_id, run_id="old"))
    assert after.run_status is RunStatus.RUNNING
    assert _codes(after) == [DiagnosticCode.STALE_RUN_EVENT]


def test_REQ_004_1_run_finished_without_outcome_sets_idle() -> None:
    """REQ-004.1: ``RUN_FINISHED`` with no outcome ends the run in ``idle``."""
    conv = _started()
    after = reduce(conv, RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id))
    assert after.run_status is RunStatus.IDLE
    check_invariants(after)


def test_REQ_004_3_run_error_sets_error_and_keeps_content() -> None:
    """REQ-004.3: ``RUN_ERROR`` sets ``error`` status and message and keeps the content."""
    conv = _started()
    after = reduce(conv, RunErrorEvent(message="boom", code="E1"))
    assert after.run_status is RunStatus.ERROR
    assert after.error == "boom"
    assert after.error_code is ErrorCode.AGENT_RUN_ERROR
    assert after.messages == conv.messages
    check_invariants(after)


def test_REQ_004_3_run_error_closes_open_streams() -> None:
    """REQ-004.3, INV-5: nothing is left streaming once the run has failed."""
    conv = _started().with_(
        messages=(
            *_started().messages,
            ChatMessage(id="m1", role=MessageRole.ASSISTANT, content="part", streaming=True),
        ),
        tool_calls=(ToolCall(id="c1", name="t", args_text='{"a"'),),
    )
    after = reduce(conv, RunErrorEvent(message="boom"))
    assert after.messages[-1].streaming is False
    assert after.messages[-1].content == "part"
    assert after.tool_calls[0].status is ToolCallStatus.ERROR
    assert after.tool_calls[0].result
    check_invariants(after)


@pytest.mark.parametrize(
    "event",
    [RunErrorEvent(message="late"), RunFinishedEvent(thread_id="t", run_id="run")],
    ids=["run-error", "run-finished"],
)
def test_REQ_004_terminal_events_after_the_run_ended_change_nothing(event: BaseEvent) -> None:
    """REQ-004: a terminal event for a run that already ended leaves the state as it is."""
    conv = _started()
    conv = reduce(conv, RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id))
    if isinstance(event, RunFinishedEvent):
        event = RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id)
    after = reduce(conv, event)
    assert after.with_(diagnostics=()) == conv
    assert _codes(after) == [DiagnosticCode.IGNORED_EVENT]
    assert after.diagnostics[0].level == "debug"


# --- steps --------------------------------------------------------------------------------


def test_REQ_010_3_step_started_and_finished_drive_current_step() -> None:
    """REQ-010.3: ``STEP_STARTED`` sets ``current_step``; its ``STEP_FINISHED`` clears it."""
    conv = reduce(_started(), StepStartedEvent(step_name="plan"))
    assert conv.current_step == "plan"
    conv = reduce(conv, StepFinishedEvent(step_name="plan"))
    assert conv.current_step == ""


def test_REQ_010_3_finishing_another_step_keeps_the_current_one() -> None:
    """REQ-010.3: only the finish of *that* step clears ``current_step``."""
    conv = reduce(_started(), StepStartedEvent(step_name="act"))
    conv = reduce(conv, StepFinishedEvent(step_name="plan"))
    assert conv.current_step == "act"


# --- tolerated events ---------------------------------------------------------------------


def test_REQ_012_1_raw_events_leave_the_state_unchanged() -> None:
    """REQ-012.1: ``RAW`` (and the activity/subagent families) only log at debug level."""
    conv = _started()
    after = reduce(conv, RawEvent(event={"x": 1}))
    assert after.with_(diagnostics=()) == conv
    assert _codes(after) == [DiagnosticCode.IGNORED_EVENT]
    assert after.diagnostics[0].event_type == "RAW"


def test_REQ_012_2_reduce_skips_an_event_type_it_has_no_handler_for() -> None:
    """REQ-012.2: ``reduce`` is total; a type without a handler is a debug diagnostic."""

    class _FutureEvent(BaseEvent):
        pass

    conv = _started()
    event = _FutureEvent.model_construct(type="FUTURE_EVENT")
    after = reduce(conv, event)
    assert after.with_(diagnostics=()) == conv
    assert _codes(after) == [DiagnosticCode.UNKNOWN_EVENT_TYPE]


# --- purity -------------------------------------------------------------------------------


def test_REQ_005_1_reduce_does_not_mutate_its_input() -> None:
    """REQ-005.1, INV-12: ``reduce`` returns a new state and leaves its input untouched."""
    conv = _started()
    snapshot = copy.deepcopy(conv)
    reduce(conv, RunErrorEvent(message="boom"))
    assert conv == snapshot


def test_REQ_005_2_reduce_is_deterministic() -> None:
    """REQ-005.2: the same events from the same state give equal states."""
    conv = _running()
    events: list[BaseEvent] = [
        RunStartedEvent(thread_id=conv.thread_id, run_id=conv.run_id),
        StepStartedEvent(step_name="s"),
        RunErrorEvent(message="x"),
    ]
    first = second = conv
    for event in events:
        first = reduce(first, event)
        second = reduce(second, event)
    assert first == second


@pytest.mark.xfail(strict=True, reason="text/tool/state/reasoning handlers land in T-011…T-013")
def test_REQ_005_1_every_known_event_type_is_handled_or_ignored() -> None:
    """REQ-005.1: the dispatch table covers the 31 AG-UI 1.0 event types."""
    from reflex_agentkit.core.reducer import HANDLED_EVENT_TYPES

    assert set(EventType) == HANDLED_EVENT_TYPES


def test_REQ_010_2_stale_run_finished_after_the_end_is_still_reported_as_stale() -> None:
    """REQ-010.2: a foreign run's ``RUN_FINISHED`` is stale even once the run has ended."""
    conv = _started()
    conv = reduce(conv, RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id))
    after = reduce(conv, RunFinishedEvent(thread_id=conv.thread_id, run_id="old"))
    assert _codes(after) == [DiagnosticCode.STALE_RUN_EVENT]
