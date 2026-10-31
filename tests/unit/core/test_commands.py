"""Pure command functions (T-015; ``begin_run``'s basic part is pulled into T-010)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from ag_ui.core import ResumeEntry
from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import (
    MAX_PAYLOAD_BYTES,
    all_answered,
    apply_approval,
    apply_cancel,
    apply_client_tool_result,
    apply_interrupt_response,
    apply_rejection,
    begin_run,
    new_thread,
    request_local_approvals,
    resume_entries,
    start_client_tool_round,
)
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    InterruptAnswer,
    MessageRole,
    OpenInterrupt,
    ReducerConfig,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)

CONFIG = ReducerConfig(client_tool_names=frozenset({"pick"}))


def _is_uuid4(value: str) -> bool:
    return str(uuid.UUID(value, version=4)) == value


def test_REQ_001_1_begin_run_appends_the_user_message() -> None:
    """REQ-001.1: the human's turn is appended as a ``user`` message with a UUID4 ID."""
    conv = begin_run(ConversationState.initial(CONFIG), user_text="hello", config=CONFIG)
    assert len(conv.messages) == 1
    msg = conv.messages[0]
    assert msg.role is MessageRole.USER
    assert msg.content == "hello"
    assert _is_uuid4(msg.id)
    check_invariants(conv)


def test_REQ_001_2_begin_run_assigns_a_new_uuid4_run_id() -> None:
    """REQ-001.2: every run gets a fresh UUID4 ``run_id``."""
    first = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    second = begin_run(first.with_(run_status=RunStatus.IDLE), user_text="b", config=CONFIG)
    assert _is_uuid4(first.run_id)
    assert _is_uuid4(second.run_id)
    assert first.run_id != second.run_id


def test_REQ_001_3_begin_run_sets_running_and_clears_the_error() -> None:
    """REQ-001.3: a starting run is ``running`` and the previous error is cleared."""
    failed = ConversationState.initial(CONFIG).with_(
        run_status=RunStatus.ERROR, error="boom", error_code=ErrorCode.AGENT_RUN_ERROR
    )
    conv = begin_run(failed, user_text="retry", config=CONFIG)
    assert conv.run_status is RunStatus.RUNNING
    assert conv.error == ""
    assert conv.error_code is None


def test_REQ_002_1_begin_run_creates_the_thread_id_lazily() -> None:
    """REQ-002.1: the first run of a thread generates a UUID4 ``thread_id``."""
    conv = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    assert _is_uuid4(conv.thread_id)


def test_REQ_002_2_begin_run_keeps_the_thread_id() -> None:
    """REQ-002.2: later runs of the thread reuse its ``thread_id``."""
    first = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    second = begin_run(first.with_(run_status=RunStatus.IDLE), user_text="b", config=CONFIG)
    assert second.thread_id == first.thread_id


def test_REQ_010_2_user_run_starts_a_new_turn_of_run_ids() -> None:
    """REQ-010.2: a user-initiated run resets ``last_run_ids`` to itself."""
    first = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    second = begin_run(first.with_(run_status=RunStatus.IDLE), user_text="b", config=CONFIG)
    assert second.last_run_ids == (second.run_id,)


def test_REQ_010_2_follow_up_run_extends_the_turn() -> None:
    """REQ-010.2: a follow-up run (no new user text) keeps the turn's earlier run IDs."""
    first = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    follow_up = begin_run(first, resume=True, config=CONFIG)
    assert follow_up.last_run_ids == (first.run_id, follow_up.run_id)
    assert len(follow_up.messages) == 1


def test_DM_3_9_begin_run_installs_the_run_config() -> None:
    """DM §3.9: the ``ReducerConfig`` is (re)built once per run."""
    conv = begin_run(ConversationState.initial(ReducerConfig()), user_text="a", config=CONFIG)
    assert conv.config is CONFIG


def test_REQ_005_2_begin_run_accepts_injected_ids() -> None:
    """REQ-005.2: ID generation can be injected, so command sequences are reproducible."""
    ids = iter(["t-1", "r-1", "m-1"])
    conv = begin_run(
        ConversationState.initial(CONFIG),
        user_text="a",
        config=CONFIG,
        new_id=lambda: next(ids),
    )
    assert (conv.thread_id, conv.run_id, conv.messages[0].id) == ("t-1", "r-1", "m-1")


# --- human in the loop (T-015) ------------------------------------------------------------


def _paused(*interrupts: OpenInterrupt, calls: tuple[ToolCall, ...] = ()) -> ConversationState:
    conv = begin_run(ConversationState.initial(CONFIG), user_text="go", config=CONFIG)
    parent = ChatMessage(
        id="m1", role=MessageRole.ASSISTANT, tool_call_ids=tuple(c.id for c in calls)
    )
    return conv.with_(
        messages=(*conv.messages, parent),
        tool_calls=calls,
        interrupts=interrupts,
        run_status=RunStatus.AWAITING_INPUT,
    )


def _pending_call(call_id: str = "c1", *, client: bool = False) -> ToolCall:
    return ToolCall(
        id=call_id,
        name="pick" if client else "book",
        args={"city": "Lisbon"},
        args_text='{"city": "Lisbon"}',
        status=ToolCallStatus.PENDING_APPROVAL,
        parent_message_id="m1",
        interrupt_id=f"local-{call_id}" if client else f"int-{call_id}",
        is_client_tool=client,
    )


def _approval(call_id: str = "c1", *, local: bool = False) -> OpenInterrupt:
    return OpenInterrupt(
        id=f"local-{call_id}" if local else f"int-{call_id}",
        reason="tool_call",
        tool_call_id=call_id,
        is_local=local,
    )


def _generic(interrupt_id: str) -> OpenInterrupt:
    return OpenInterrupt(id=interrupt_id, reason="human_input")


def test_REQ_013_2_approve_records_the_answer_and_runs_the_call() -> None:
    """REQ-013.2: approval records ``{"approved": true}`` and sets ``running``."""
    conv = apply_approval(_paused(_approval(), calls=(_pending_call(),)), "c1")
    assert conv.answers == {
        "int-c1": InterruptAnswer(
            interrupt_id="int-c1", status="resolved", payload={"approved": True}
        )
    }
    assert conv.tool_calls[0].status is ToolCallStatus.RUNNING
    check_invariants(conv)


def test_REQ_013_5_answering_the_last_interrupt_leaves_the_pause() -> None:
    """REQ-013.5, INV-4: with every interrupt answered the run is ready to resume."""
    conv = apply_approval(_paused(_approval(), calls=(_pending_call(),)), "c1")
    assert all_answered(conv)
    assert conv.run_status is RunStatus.IDLE


def test_REQ_013_5_partial_answers_keep_awaiting_input() -> None:
    """REQ-013.5: the run resumes only when every interrupt has an answer."""
    conv = _paused(_approval(), _generic("i1"), calls=(_pending_call(),))
    conv = apply_approval(conv, "c1")
    assert not all_answered(conv)
    assert conv.run_status is RunStatus.AWAITING_INPUT
    check_invariants(conv)


@pytest.mark.parametrize("edited", [{"city": "Porto"}, '{"city": "Porto"}'], ids=["dict", "str"])
def test_REQ_013_3_approve_with_edited_args_records_payload(edited: object) -> None:
    """REQ-013.3: edits are recorded as ``editedArgs`` and shown as the call's args."""
    conv = apply_approval(_paused(_approval(), calls=(_pending_call(),)), "c1", edited)
    assert conv.answers["int-c1"].payload == {"approved": True, "editedArgs": {"city": "Porto"}}
    assert conv.tool_calls[0].args == {"city": "Porto"}


@pytest.mark.parametrize(
    "edited",
    [[1, 2], "not json", '"a string"', {"big": "x" * MAX_PAYLOAD_BYTES}],
    ids=["list", "bad-json", "json-non-object", "too-large"],
)
def test_REQ_013_7_invalid_edited_args_keep_the_call_pending(edited: object) -> None:
    """REQ-013.7, TD §6: non-object or oversized edits are rejected; the call stays pending."""
    before = _paused(_approval(), calls=(_pending_call(),))
    conv = apply_approval(before, "c1", edited)
    assert conv.error_code is ErrorCode.INVALID_EDITED_ARGS
    assert conv.error
    assert conv.tool_calls == before.tool_calls
    assert conv.answers == {}
    assert conv.run_status is RunStatus.AWAITING_INPUT


def test_REQ_013_4_reject_records_the_answer_with_reason() -> None:
    """REQ-013.4: rejection records ``approved: false`` with the reason; status ``rejected``."""
    conv = apply_rejection(_paused(_approval(), calls=(_pending_call(),)), "c1", "no")
    assert conv.answers["int-c1"].payload == {"approved": False, "reason": "no"}
    assert conv.tool_calls[0].status is ToolCallStatus.REJECTED
    assert conv.tool_calls[0].result == "Rejected by the user: no"


def test_REQ_013_4_reject_without_reason_omits_it() -> None:
    """REQ-013.4: the reason key is omitted when ``None``."""
    conv = apply_rejection(_paused(_approval(), calls=(_pending_call(),)), "c1")
    assert conv.answers["int-c1"].payload == {"approved": False}
    assert conv.tool_calls[0].result == "Rejected by the user."


def test_REQ_018_3_rejecting_a_client_tool_adds_a_rejection_result_message() -> None:
    """REQ-018.3: a local approval is answered locally with a rejection tool message."""
    conv = _paused(_approval(local=True), calls=(_pending_call(client=True),))
    conv = apply_rejection(conv, "c1", "nope", new_id=lambda: "t-1")
    tool_msg = conv.messages[-1]
    assert (tool_msg.id, tool_msg.role, tool_msg.tool_call_id, tool_msg.is_error) == (
        "t-1",
        MessageRole.TOOL,
        "c1",
        True,
    )
    assert tool_msg.content == "Rejected by the user: nope"
    check_invariants(conv)


@pytest.mark.parametrize("command", ["approve", "reject"])
def test_REQ_013_6_unknown_or_non_pending_calls_are_ignored(command: str) -> None:
    """REQ-013.6: commands for calls that are not ``pending_approval`` are no-ops."""
    done = ToolCall(id="c2", name="t", status=ToolCallStatus.DONE, parent_message_id="m1")
    conv = _paused(_approval(), calls=(_pending_call(), done))
    for call_id in ("ghost", "c2"):
        after = (
            apply_approval(conv, call_id)
            if command == "approve"
            else apply_rejection(conv, call_id)
        )
        assert after is conv


def test_REQ_014_2_respond_answers_the_first_pending_generic_interrupt() -> None:
    """REQ-014.2-3: answers go to generic interrupts one at a time, in arrival order."""
    conv = _paused(_generic("i1"), _generic("i2"))
    conv = apply_interrupt_response(conv, "Lisbon")
    assert conv.answers["i1"].payload == "Lisbon"
    conv = apply_interrupt_response(conv, '{"ok": true}')
    assert conv.answers["i2"].payload == {"ok": True}
    assert conv.run_status is RunStatus.IDLE


def test_REQ_014_2_respond_skips_approvals() -> None:
    """REQ-014.2: approvals are answered by approve/reject, never by a response."""
    conv = _paused(_approval(), _generic("i1"), calls=(_pending_call(),))
    conv = apply_interrupt_response(conv, 1)
    assert set(conv.answers) == {"i1"}


def test_REQ_014_4_respond_without_a_pending_interrupt_is_ignored() -> None:
    """REQ-014.4: with no generic interrupt pending, a response is a no-op."""
    conv = _paused(_approval(), calls=(_pending_call(),))
    assert apply_interrupt_response(conv, "x") is conv


def test_REQ_014_2_oversized_response_is_ignored_with_a_warning() -> None:
    """TD §6: interrupt payloads above 64 KiB are ignored with a warning."""
    conv = apply_interrupt_response(_paused(_generic("i1")), "x" * (MAX_PAYLOAD_BYTES + 1))
    assert conv.answers == {}
    assert [d.level for d in conv.diagnostics] == ["warning"]


def test_REQ_007_4_cancel_while_running_keeps_partial_content() -> None:
    """REQ-007.4: partial text is kept; streaming and running calls become ``error``."""
    conv = begin_run(ConversationState.initial(CONFIG), user_text="go", config=CONFIG)
    conv = conv.with_(
        messages=(
            *conv.messages,
            ChatMessage(
                id="m1",
                role=MessageRole.ASSISTANT,
                content="part",
                streaming=True,
                tool_call_ids=("c1", "c2", "c3"),
            ),
        ),
        tool_calls=(
            ToolCall(id="c1", name="a", parent_message_id="m1"),
            ToolCall(id="c2", name="b", status=ToolCallStatus.RUNNING, parent_message_id="m1"),
            ToolCall(
                id="c3", name="c", status=ToolCallStatus.DONE, result="ok", parent_message_id="m1"
            ),
        ),
    )
    after = apply_cancel(conv)
    assert after.run_status is RunStatus.CANCELLED
    assert after.messages[-1].content == "part"
    assert after.messages[-1].streaming is False
    assert [(c.status, c.result) for c in after.tool_calls] == [
        (ToolCallStatus.ERROR, "cancelled"),
        (ToolCallStatus.ERROR, "cancelled"),
        (ToolCallStatus.DONE, "ok"),
    ]
    check_invariants(after)


def test_REQ_015_2_cancel_while_paused_rejects_and_remembers_interrupts() -> None:
    """REQ-015.2: open approvals are rejected; non-local interrupt IDs are remembered."""
    conv = _paused(
        _approval(),
        _approval("c2", local=True),
        _generic("i1"),
        calls=(_pending_call(), _pending_call("c2", client=True)),
    )
    conv = apply_interrupt_response(conv, "answered first")
    after = apply_cancel(conv)
    assert after.run_status is RunStatus.CANCELLED
    assert [c.status for c in after.tool_calls] == [ToolCallStatus.REJECTED] * 2
    assert after.interrupts == ()
    assert after.answers == {}
    assert after.abandoned_interrupt_ids == ("int-c1", "i1")
    check_invariants(after)


def test_REQ_007_cancel_in_other_states_is_a_no_op() -> None:
    """API §4.3: ``cancel_run`` outside ``running``/``awaiting_input`` changes nothing."""
    idle = ConversationState.initial(CONFIG)
    assert apply_cancel(idle) is idle


def test_REQ_015_3_next_run_cancels_the_abandoned_interrupts() -> None:
    """REQ-015.3: the next run carries a ``cancelled`` entry per remembered interrupt."""
    conv = apply_cancel(_paused(_approval(), _generic("i1"), calls=(_pending_call(),)))
    conv = begin_run(conv, user_text="never mind", config=CONFIG)
    assert resume_entries(conv) == [
        ResumeEntry(interrupt_id="int-c1", status="cancelled"),
        ResumeEntry(interrupt_id="i1", status="cancelled"),
    ]
    assert conv.abandoned_interrupt_ids == ()


def test_REQ_013_5_begin_run_captures_resume_entries_and_clears_the_pause() -> None:
    """REQ-013.5, DM §3.10 v1.6: resolved entries in interrupt order; locals excluded."""
    conv = _paused(
        _generic("i1"),
        _approval(),
        _approval("c2", local=True),
        calls=(_pending_call(), _pending_call("c2", client=True)),
    )
    conv = apply_approval(apply_approval(apply_interrupt_response(conv, 7), "c1"), "c2")
    conv = begin_run(conv, resume=True, config=CONFIG)
    assert resume_entries(conv) == [
        ResumeEntry(interrupt_id="i1", status="resolved", payload=7),
        ResumeEntry(interrupt_id="int-c1", status="resolved", payload={"approved": True}),
    ]
    assert (conv.interrupts, conv.answers) == ((), {})
    assert conv.run_status is RunStatus.RUNNING
    check_invariants(conv)


def test_REQ_018_2_client_tool_result_completes_the_call() -> None:
    """REQ-018.2: the handler's result is stored, ``done``, with a tool message."""
    call = ToolCall(
        id="c1",
        name="pick",
        status=ToolCallStatus.RUNNING,
        is_client_tool=True,
        parent_message_id="m1",
        args={},
    )
    conv = _paused(calls=(call,)).with_(run_status=RunStatus.RUNNING)
    conv = apply_client_tool_result(conv, "c1", "2026-05-01", new_id=lambda: "t-1")
    assert (conv.tool_calls[0].status, conv.tool_calls[0].result) == (
        ToolCallStatus.DONE,
        "2026-05-01",
    )
    assert conv.messages[-1] == ChatMessage(
        id="t-1", role=MessageRole.TOOL, content="2026-05-01", tool_call_id="c1"
    )
    check_invariants(conv)


def test_REQ_018_4_client_tool_error_is_a_tool_result_not_a_run_error() -> None:
    """REQ-018.4: a failing handler sets the call to ``error``; the run continues."""
    call = ToolCall(
        id="c1",
        name="pick",
        status=ToolCallStatus.RUNNING,
        is_client_tool=True,
        parent_message_id="m1",
        args={},
    )
    conv = _paused(calls=(call,)).with_(run_status=RunStatus.RUNNING)
    conv = apply_client_tool_result(conv, "c1", "boom", is_error=True)
    assert conv.tool_calls[0].status is ToolCallStatus.ERROR
    assert conv.messages[-1].is_error is True
    assert conv.run_status is RunStatus.RUNNING
    assert conv.error_code is None


def test_REQ_018_2_client_tool_result_for_a_non_running_call_is_ignored() -> None:
    """REQ-018.2: only a running client-tool call takes a handler result."""
    conv = _paused(_approval(), calls=(_pending_call(),))
    assert apply_client_tool_result(conv, "c1", "x") is conv
    assert apply_client_tool_result(conv, "ghost", "x") is conv


def _running_client_call(call_id: str = "c1") -> ToolCall:
    return ToolCall(
        id=call_id,
        name="pick",
        status=ToolCallStatus.RUNNING,
        is_client_tool=True,
        parent_message_id="m1",
        args={"day": 1},
    )


def test_REQ_018_3_local_approval_pauses_with_a_local_interrupt() -> None:
    """REQ-018.3, DM §3.4: an approval-required client tool waits on a local interrupt."""
    calls = (_running_client_call("c1"), _running_client_call("c2"))
    conv = _paused(calls=calls).with_(run_status=RunStatus.RUNNING)
    conv = request_local_approvals(conv, ["c1"])
    assert conv.run_status is RunStatus.AWAITING_INPUT
    assert conv.interrupts == (
        OpenInterrupt(id="local-c1", reason="tool_call", tool_call_id="c1", is_local=True),
    )
    assert conv.answers == {}
    first, second = conv.tool_calls
    assert (first.status, first.interrupt_id) == (ToolCallStatus.PENDING_APPROVAL, "local-c1")
    assert second.status is ToolCallStatus.RUNNING
    check_invariants(conv)


def test_REQ_018_3_local_approval_round_trip_runs_the_call_locally() -> None:
    """REQ-018.3: approving it makes the call ``running`` and never adds a resume entry."""
    conv = _paused(calls=(_running_client_call(),)).with_(run_status=RunStatus.RUNNING)
    conv = apply_approval(request_local_approvals(conv, ["c1"]), "c1", {"day": 9})
    assert conv.run_status is RunStatus.IDLE
    assert conv.tool_calls[0].status is ToolCallStatus.RUNNING
    assert conv.tool_calls[0].args == {"day": 9}
    resumed = begin_run(conv, config=CONFIG, resume=True)
    assert resume_entries(resumed) == []


@pytest.mark.parametrize("call_ids", [[], ["ghost"]])
def test_REQ_018_3_local_approval_without_a_running_client_call_is_a_no_op(
    call_ids: list[str],
) -> None:
    """REQ-018.3: nothing to approve leaves the conversation unchanged."""
    conv = _paused(calls=(_running_client_call(),)).with_(run_status=RunStatus.RUNNING)
    assert request_local_approvals(conv, call_ids) is conv
    paused = _paused(_approval(), calls=(_pending_call(),))
    assert request_local_approvals(paused, ["c1"]) is paused


def test_DD_009_client_tool_rounds_are_counted() -> None:
    """DD-009: each client-tool round increments the counter while under the limit."""
    conv = _paused(calls=(_running_client_call(),)).with_(run_status=RunStatus.RUNNING)
    conv = start_client_tool_round(conv, max_rounds=2)
    conv = start_client_tool_round(conv, max_rounds=2)
    assert (conv.client_tool_rounds, conv.run_status) == (2, RunStatus.RUNNING)


def test_DD_009_exceeding_the_round_limit_is_a_run_error() -> None:
    """DD-009: one round more than ``max_client_tool_rounds`` ends the run in ``error``."""
    conv = _paused(calls=(_running_client_call(),)).with_(
        run_status=RunStatus.RUNNING, client_tool_rounds=2
    )
    conv = start_client_tool_round(conv, max_rounds=2)
    assert conv.run_status is RunStatus.ERROR
    assert conv.error_code is ErrorCode.CLIENT_TOOL_LOOP_LIMIT
    assert "2" in conv.error
    check_invariants(conv)


def test_DD_009_round_counter_resets_on_a_user_turn() -> None:
    """DM §3.9: a user-initiated ``begin_run`` resets the round counter."""
    conv = ConversationState.initial(CONFIG).with_(client_tool_rounds=5)
    assert begin_run(conv, config=CONFIG, user_text="hi").client_tool_rounds == 0


def test_REQ_002_3_new_thread_resets_the_conversation() -> None:
    """REQ-002.3: a new thread clears everything and gets a new ``thread_id``."""
    conv = apply_cancel(_paused(_approval(), calls=(_pending_call(),))).with_(
        shared_state={"a": 1}, error="x"
    )
    fresh = new_thread(conv, new_id=lambda: "t-new")
    assert fresh == ConversationState.initial(CONFIG).with_(thread_id="t-new")


def test_REQ_002_4_new_thread_cancels_a_running_run_first() -> None:
    """REQ-002.4: a running run is cancelled before the thread is reset."""
    conv = begin_run(ConversationState.initial(CONFIG), user_text="go", config=CONFIG)
    fresh = new_thread(conv, new_id=lambda: "t-new")
    assert fresh.run_status is RunStatus.IDLE
    assert fresh.messages == ()


def test_DM_3_10_user_turn_resets_client_tool_rounds() -> None:
    """DM §3.10: a user-initiated run resets ``client_tool_rounds``; follow-ups keep it."""
    conv = ConversationState.initial(CONFIG).with_(client_tool_rounds=3)
    assert begin_run(conv, resume=True, config=CONFIG).client_tool_rounds == 3
    assert begin_run(conv, user_text="hi", config=CONFIG).client_tool_rounds == 0


def test_REQ_013_3_edited_args_payload_is_json_serializable() -> None:
    """API §7.4: the recorded payload is plain JSON."""
    conv = apply_approval(_paused(_approval(), calls=(_pending_call(),)), "c1", {"n": [1]})
    json.dumps(conv.answers["int-c1"].payload)


@pytest.mark.parametrize("edited", ['{"n": NaN}', {"x": {1, 2}}], ids=["nan", "unserializable"])
def test_REQ_013_7_non_json_edits_are_rejected(edited: object) -> None:
    """REQ-013.7: NaN and values JSON cannot encode are not valid edited arguments."""
    conv = apply_approval(_paused(_approval(), calls=(_pending_call(),)), "c1", edited)
    assert conv.error_code is ErrorCode.INVALID_EDITED_ARGS


def test_REQ_014_2_unserializable_response_is_ignored_with_a_warning() -> None:
    """TD §6: a response JSON cannot encode is ignored with a warning."""
    conv = apply_interrupt_response(_paused(_generic("i1")), {1, 2})
    assert conv.answers == {}
    assert [d.level for d in conv.diagnostics] == ["warning"]


def test_REQ_013_6_commands_outside_a_pause_are_ignored() -> None:
    """REQ-013.6: approvals and responses apply only while ``awaiting_input``."""
    conv = _paused(_approval(), calls=(_pending_call(),)).with_(run_status=RunStatus.RUNNING)
    assert apply_approval(conv, "c1") is conv
    assert apply_interrupt_response(conv, "x") is conv


@pytest.mark.parametrize("start", [{"user_text": "hi"}, {"resume": True}], ids=["user", "resume"])
def test_REQ_015_1_begin_run_while_paused_is_a_no_op(start: dict[str, Any]) -> None:
    """REQ-015.1, INV-6: a run cannot start while an interrupt is unanswered."""
    conv = _paused(_approval(), calls=(_pending_call(),))
    assert begin_run(conv, config=CONFIG, **start) is conv


def test_REQ_004_4_failure_keeps_partial_content_and_closes_streams() -> None:
    """TD Flow E: a transport failure ends the run in ``error``; content is kept."""
    from reflex_agentkit.core.commands import apply_failure
    from reflex_agentkit.core.reducer import INCOMPLETE_TOOL_CALL

    conv = begin_run(ConversationState.initial(CONFIG), user_text="go", config=CONFIG)
    conv = conv.with_(
        messages=(
            *conv.messages,
            ChatMessage(
                id="m1",
                role=MessageRole.ASSISTANT,
                content="part",
                streaming=True,
                tool_call_ids=("c1",),
            ),
        ),
        tool_calls=(ToolCall(id="c1", name="t", parent_message_id="m1"),),
        dirty_tool_args=frozenset({"c1"}),
    )
    after = apply_failure(conv, ErrorCode.AGENT_STREAM_ERROR, "stream ended unexpectedly")
    assert (after.run_status, after.error_code, after.error) == (
        RunStatus.ERROR,
        ErrorCode.AGENT_STREAM_ERROR,
        "stream ended unexpectedly",
    )
    assert after.messages[-1].content == "part"
    assert after.messages[-1].streaming is False
    assert (after.tool_calls[0].status, after.tool_calls[0].result) == (
        ToolCallStatus.ERROR,
        INCOMPLETE_TOOL_CALL,
    )
    check_invariants(after)


def test_REQ_004_4_failure_outside_a_running_run_is_a_no_op() -> None:
    """A failure reported after the run already ended changes nothing."""
    from reflex_agentkit.core.commands import apply_failure

    idle = ConversationState.initial(CONFIG)
    assert apply_failure(idle, ErrorCode.AGENT_STREAM_ERROR, "x") is idle
