"""The projection of a conversation onto the public vars (T-029, DM §7.2)."""

from __future__ import annotations

from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import apply_interrupt_response, begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    CustomEventRecord,
    MessageRole,
    OpenInterrupt,
    PendingInterrupt,
    ReasoningRecord,
    ReducerConfig,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from reflex_agentkit.state._projection import project, refresh_dirty_args

CONFIG = ReducerConfig()


def _conv(**changes: object) -> ConversationState:
    return ConversationState.initial(CONFIG).with_(**changes)


def test_DM_7_2_messages_keep_user_assistant_and_tool_roles_only() -> None:
    """DM §7.2: system and developer messages never reach the browser."""
    messages = (
        ChatMessage(id="s", role=MessageRole.SYSTEM, content="be nice"),
        ChatMessage(id="d", role=MessageRole.DEVELOPER, content="internal"),
        ChatMessage(id="u", role=MessageRole.USER, content="hi"),
        ChatMessage(id="a", role=MessageRole.ASSISTANT, content="hello"),
        ChatMessage(id="t", role=MessageRole.TOOL, content="42", tool_call_id="c1"),
    )
    view = project(_conv(messages=messages))
    assert [m.id for m in view.messages] == ["u", "a", "t"]
    assert isinstance(view.messages, list)


def test_INV_11_reasoning_content_is_projected_and_encrypted_value_never() -> None:
    """DM §7.2, INV-11: ``reasoning`` is filled in; ``encrypted_value`` never appears."""
    messages = (ChatMessage(id="a", role=MessageRole.ASSISTANT, content="answer"),)
    reasoning = (
        ReasoningRecord(
            id="r1", assistant_message_id="a", content="thinking", encrypted_value="ENC-SECRET"
        ),
    )
    view = project(_conv(messages=messages, reasoning=reasoning))
    assert view.messages[0].reasoning == "thinking"
    assert "ENC-SECRET" not in repr(view)


def test_DM_7_2_scalar_fields_and_lists_are_copied() -> None:
    """DM §7.2: same-named fields; tuples become lists (R-5)."""
    call = ToolCall(id="c1", name="search", status=ToolCallStatus.DONE, result="x")
    record = CustomEventRecord(name="progress", value=1, run_id="r")
    conv = _conv(
        thread_id="t",
        run_id="r",
        run_status=RunStatus.ERROR,
        error="boom",
        error_code=ErrorCode.AGENT_RUN_ERROR,
        current_step="plan",
        tool_calls=(call,),
        shared_state={"a": 1},
        shared_state_stale=True,
        custom_events=(record,),
    )
    view = project(conv)
    assert (view.thread_id, view.run_id, view.current_step) == ("t", "r", "plan")
    assert (view.run_status, view.error, view.error_code) == (
        RunStatus.ERROR,
        "boom",
        ErrorCode.AGENT_RUN_ERROR,
    )
    assert view.tool_calls == [call]
    assert view.custom_events == [record]
    assert (view.shared_state, view.shared_state_stale) == ({"a": 1}, True)
    view.shared_state["b"] = 2  # the projection owns its copy
    assert conv.shared_state == {"a": 1}


def _generic(interrupt_id: str) -> OpenInterrupt:
    return OpenInterrupt(id=interrupt_id, reason="confirm", message=f"ok {interrupt_id}?")


def test_REQ_014_3_pending_interrupt_shows_the_queue_position() -> None:
    """REQ-014.3: generic interrupts are presented one at a time, in order."""
    conv = begin_run(ConversationState.initial(CONFIG), config=CONFIG, user_text="go").with_(
        run_status=RunStatus.AWAITING_INPUT,
        interrupts=(
            OpenInterrupt(id="local-c1", reason="tool_call", tool_call_id="c1", is_local=True),
            _generic("i1"),
            _generic("i2"),
        ),
    )
    assert project(conv).pending_interrupt == PendingInterrupt(
        id="i1",
        reason="confirm",
        message="ok i1?",
        payload=None,
        response_schema=None,
        queue_position=1,
        queue_size=2,
    )
    answered = apply_interrupt_response(conv, "yes")
    pending = project(answered).pending_interrupt
    assert pending is not None
    assert (pending.id, pending.queue_position, pending.queue_size) == ("i2", 2, 2)


def test_REQ_014_2_no_pending_interrupt_for_approvals_only() -> None:
    """DM §7.2: approvals and local interrupts are not generic interrupts."""
    conv = _conv(
        run_status=RunStatus.AWAITING_INPUT,
        interrupts=(OpenInterrupt(id="int-c1", reason="tool_call", tool_call_id="c1"),),
    )
    assert project(conv).pending_interrupt is None
    assert project(_conv()).pending_interrupt is None


def test_DM_H_3_dirty_args_are_parsed_when_valid_and_the_set_is_cleared() -> None:
    """DM H-3: streaming args are parsed once per flush, when they are valid JSON."""
    calls = (
        ToolCall(id="c1", name="a", args_text='{"q": "lis', status=ToolCallStatus.STREAMING),
        ToolCall(id="c2", name="b", args_text='{"q": "lisbon"}', status=ToolCallStatus.STREAMING),
        ToolCall(id="c3", name="c", args_text="[1, 2]", status=ToolCallStatus.STREAMING),
    )
    conv = _conv(
        run_status=RunStatus.RUNNING,
        tool_calls=calls,
        dirty_tool_args=frozenset({"c1", "c2", "c3"}),
    )
    refreshed = refresh_dirty_args(conv)
    assert [c.args for c in refreshed.tool_calls] == [None, {"q": "lisbon"}, None]
    assert refreshed.dirty_tool_args == frozenset()
    assert refresh_dirty_args(refreshed) is refreshed
    assert project(conv).tool_calls[1].args == {"q": "lisbon"}
    check_invariants(refreshed)
