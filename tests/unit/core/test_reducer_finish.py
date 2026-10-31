"""Reducer: ``RUN_FINISHED`` outcomes (T-014; REQ-004.1-2, REQ-013.1, REQ-014.1/3)."""

from __future__ import annotations

from typing import Any

from ag_ui.core import (
    BaseEvent,
    EventType,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunStartedEvent,
    TextMessageContentEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import (
    DiagnosticCode,
    OpenInterrupt,
    ReducerConfig,
    RunStatus,
    ToolCallStatus,
)
from reflex_agentkit.core.reducer import reduce

CONFIG = ReducerConfig(client_tool_names=frozenset({"pick_date"}))


def _started() -> ConversationState:
    conv = begin_run(ConversationState.initial(CONFIG), user_text="hi", config=CONFIG)
    return reduce(conv, RunStartedEvent(thread_id=conv.thread_id, run_id=conv.run_id))


def _apply(conv: ConversationState, *events: BaseEvent) -> ConversationState:
    for event in events:
        conv = reduce(conv, event)
    check_invariants(conv)
    return conv


def _finish(conv: ConversationState, outcome: dict[str, Any] | None = None) -> RunFinishedEvent:
    payload: dict[str, Any] = {"threadId": conv.thread_id, "runId": conv.run_id}
    if outcome is not None:
        payload["outcome"] = outcome
    return RunFinishedEvent.model_validate(payload)


def _with_call(name: str = "book_hotel", call_id: str = "c1") -> ConversationState:
    return _apply(
        _started(),
        ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name, parent_message_id="m1"),
        ToolCallEndEvent(tool_call_id=call_id),
    )


def _codes(conv: ConversationState) -> list[DiagnosticCode]:
    return [d.code for d in conv.diagnostics]


def test_REQ_004_1_success_outcome_sets_idle() -> None:
    """REQ-004.1: ``outcome.type == "success"`` ends the run in ``idle``."""
    conv = _started()
    assert _apply(conv, _finish(conv, {"type": "success"})).run_status is RunStatus.IDLE


def test_REQ_004_1_pending_client_tool_keeps_the_run_running() -> None:
    """REQ-004.1, REQ-018.2: client-tool calls awaiting execution keep ``running``."""
    conv = _with_call("pick_date")
    after = _apply(conv, _finish(conv))
    assert after.run_status is RunStatus.RUNNING
    assert after.tool_calls[0].status is ToolCallStatus.RUNNING


def test_REQ_004_1_pending_tool_call_ids_keep_the_run_running() -> None:
    """A-18: ``pending_tool_call_ids`` naming known calls also keeps ``running``."""
    conv = _with_call("unregistered_frontend_tool")
    after = _apply(conv, _finish(conv, {"type": "success", "pendingToolCallIds": ["c1"]}))
    assert after.run_status is RunStatus.RUNNING


def test_REQ_004_1_pending_ids_of_unknown_calls_do_not_hold_the_run() -> None:
    """A-18: only known calls can hold the run open."""
    conv = _started()
    after = _apply(conv, _finish(conv, {"type": "success", "pendingToolCallIds": ["ghost"]}))
    assert after.run_status is RunStatus.IDLE


def test_REQ_004_1_finished_client_tool_does_not_hold_the_run() -> None:
    """REQ-004.1: a client tool that already has its result does not keep ``running``."""
    conv = _with_call("pick_date")
    done = conv.tool_calls[0].__class__(
        id="c1",
        name="pick_date",
        status=ToolCallStatus.DONE,
        is_client_tool=True,
        parent_message_id="m1",
        args={},
        result="ok",
    )
    conv = conv.with_(tool_calls=(done,))
    assert _apply(conv, _finish(conv)).run_status is RunStatus.IDLE


def test_REQ_013_1_tool_call_interrupt_pends_the_call() -> None:
    """REQ-013.1: a ``tool_call`` interrupt sets ``pending_approval`` and the interrupt ID."""
    conv = _with_call()
    after = _apply(
        conv,
        _finish(
            conv,
            {
                "type": "interrupt",
                "interrupts": [{"id": "int-c1", "reason": "tool_call", "toolCallId": "c1"}],
            },
        ),
    )
    assert after.run_status is RunStatus.AWAITING_INPUT
    assert after.tool_calls[0].status is ToolCallStatus.PENDING_APPROVAL
    assert after.tool_calls[0].interrupt_id == "int-c1"
    assert after.interrupts == (OpenInterrupt(id="int-c1", reason="tool_call", tool_call_id="c1"),)
    assert after.answers == {}


def test_REQ_014_1_generic_interrupts_are_kept_in_arrival_order() -> None:
    """REQ-014.1, REQ-014.3: generic interrupts are stored in order with their fields."""
    conv = _started()
    after = _apply(
        conv,
        _finish(
            conv,
            {
                "type": "interrupt",
                "interrupts": [
                    {
                        "id": "i1",
                        "reason": "human_input",
                        "message": "City?",
                        "responseSchema": {"type": "string"},
                        "metadata": {"langgraph": {"raw": {"q": "City?"}}},
                    },
                    {"id": "i2", "reason": "confirm", "metadata": {"other": 1}},
                ],
            },
        ),
    )
    assert after.interrupts == (
        OpenInterrupt(
            id="i1",
            reason="human_input",
            message="City?",
            payload={"q": "City?"},
            response_schema={"type": "string"},
        ),
        OpenInterrupt(id="i2", reason="confirm"),
    )
    assert after.run_status is RunStatus.AWAITING_INPUT


def test_REQ_013_1_tool_call_interrupt_for_an_unknown_call_becomes_generic() -> None:
    """DM §7.2 v1.5: an approval for an unknown call is kept answerable as generic."""
    conv = _started()
    after = _apply(
        conv,
        _finish(
            conv,
            {
                "type": "interrupt",
                "interrupts": [{"id": "x", "reason": "tool_call", "toolCallId": "ghost"}],
            },
        ),
    )
    assert after.interrupts == (OpenInterrupt(id="x", reason="tool_call"),)
    assert after.run_status is RunStatus.AWAITING_INPUT
    assert _codes(after) == [DiagnosticCode.UNKNOWN_TOOL_CALL_ID]


def test_REQ_014_3_repeated_interrupt_ids_keep_the_first() -> None:
    """INV-1: a repeated interrupt ID is dropped with a warning."""
    conv = _started()
    after = _apply(
        conv,
        _finish(
            conv,
            {
                "type": "interrupt",
                "interrupts": [{"id": "i", "reason": "a"}, {"id": "i", "reason": "b"}],
            },
        ),
    )
    assert [i.reason for i in after.interrupts] == ["a"]
    assert _codes(after) == [DiagnosticCode.DUPLICATE_ID]


def test_REQ_004_2_interrupt_outcome_without_interrupts_is_a_success() -> None:
    """INV-4, REQ-005.1: an interrupt outcome with nothing to answer cannot pause the run.

    The protocol rejects an empty list at validation; ``reduce`` stays total anyway.
    """
    conv = _started()
    outcome = RunFinishedInterruptOutcome.model_construct(type="interrupt", interrupts=[])
    event = RunFinishedEvent.model_construct(
        type=EventType.RUN_FINISHED, thread_id=conv.thread_id, run_id=conv.run_id, outcome=outcome
    )
    after = _apply(conv, event)
    assert after.run_status is RunStatus.IDLE
    assert after.interrupts == ()


def test_REQ_004_2_cancelled_outcome_sets_cancelled_and_closes_streams() -> None:
    """API §8.3: ``outcome.type == "cancelled"`` ends the run as ``cancelled``."""
    conv = _apply(
        _started(),
        TextMessageContentEvent(message_id="m1", delta="part"),
        ToolCallStartEvent(tool_call_id="c1", tool_call_name="t", parent_message_id="m1"),
    )
    after = _apply(conv.with_(diagnostics=()), _finish(conv, {"type": "cancelled"}))
    assert after.run_status is RunStatus.CANCELLED
    assert after.messages[1].streaming is False
    assert after.tool_calls[0].status is ToolCallStatus.ERROR
