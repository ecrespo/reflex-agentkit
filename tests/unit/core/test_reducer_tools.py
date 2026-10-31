"""Reducer: tool call events (T-012, REQ-009, REQ-018.2 marking)."""

from __future__ import annotations

import pytest
from ag_ui.core import (
    BaseEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallChunkEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import (
    DiagnosticCode,
    MessageRole,
    ReducerConfig,
    ToolCall,
    ToolCallStatus,
)
from reflex_agentkit.core.reducer import INVALID_TOOL_ARGUMENTS, reduce

CONFIG = ReducerConfig(client_tool_names=frozenset({"pick_date"}), max_args_bytes=64)


def _started(config: ReducerConfig = CONFIG) -> ConversationState:
    conv = begin_run(ConversationState.initial(config), user_text="hi", config=config)
    return reduce(conv, RunStartedEvent(thread_id=conv.thread_id, run_id=conv.run_id))


def _apply(conv: ConversationState, *events: BaseEvent) -> ConversationState:
    for event in events:
        conv = reduce(conv, event)
    check_invariants(conv)
    return conv


def _call(conv: ConversationState, call_id: str = "c1") -> ToolCall:
    return conv.tool_calls[conv._tool_index[call_id]]


def _codes(conv: ConversationState) -> list[DiagnosticCode]:
    return [d.code for d in conv.diagnostics]


def _start(call_id: str = "c1", name: str = "get_weather", parent: str | None = "m1") -> BaseEvent:
    return ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name, parent_message_id=parent)


# --- START ---------------------------------------------------------------------------------


def test_REQ_009_1_start_adds_a_streaming_call_linked_to_its_parent() -> None:
    """REQ-009.1: START adds the call (streaming, empty args) and links its parent."""
    conv = _apply(_started(), TextMessageStartEvent(message_id="m1"), _start())
    assert _call(conv) == ToolCall(
        id="c1", name="get_weather", status=ToolCallStatus.STREAMING, parent_message_id="m1"
    )
    assert conv.messages[1].tool_call_ids == ("c1",)


def test_REQ_009_1_start_creates_a_missing_parent_message() -> None:
    """REQ-009.1, DM §7.3: a call whose parent never streamed text still gets a parent."""
    conv = _apply(_started(), _start(parent="m9"))
    parent = conv.messages[conv._message_index["m9"]]
    assert parent.role is MessageRole.ASSISTANT
    assert parent.content == ""
    assert parent.streaming is False
    assert parent.tool_call_ids == ("c1",)
    assert conv.diagnostics == ()


def test_REQ_009_1_start_without_parent_joins_the_last_assistant_message() -> None:
    """REQ-009.1: with no ``parentMessageId`` the call joins the turn's assistant message."""
    conv = _apply(_started(), TextMessageStartEvent(message_id="m1"), _start(parent=None))
    assert _call(conv).parent_message_id == "m1"
    assert conv.messages[1].tool_call_ids == ("c1",)


def test_REQ_009_1_start_without_parent_after_the_user_turn_creates_one() -> None:
    """REQ-009.1: with no assistant message in the turn yet, a deterministic one is made."""
    conv = _apply(_started(), _start(parent=None))
    assert _call(conv).parent_message_id == "assistant-c1"
    assert conv.messages[-1].tool_call_ids == ("c1",)


def test_REQ_009_1_duplicate_start_is_a_warning() -> None:
    """INV-1: a second START for the same call ID is ignored with a warning."""
    conv = _apply(_started(), _start(), _start(name="other"))
    assert len(conv.tool_calls) == 1
    assert _call(conv).name == "get_weather"
    assert _codes(conv) == [DiagnosticCode.DUPLICATE_ID]


def test_REQ_018_2_start_marks_client_tools() -> None:
    """REQ-018.2: calls to registered client-side tools are marked at START."""
    conv = _apply(_started(), _start("c1", "pick_date"), _start("c2", "get_weather"))
    assert _call(conv, "c1").is_client_tool is True
    assert _call(conv, "c2").is_client_tool is False


# --- ARGS / END ----------------------------------------------------------------------------


def test_REQ_009_2_args_accumulate_and_mark_the_call_dirty() -> None:
    """REQ-009.2, DM H-3: deltas accumulate; parsing is deferred to projection or END."""
    conv = _apply(
        _started(),
        _start(),
        ToolCallArgsEvent(tool_call_id="c1", delta='{"city": '),
        ToolCallArgsEvent(tool_call_id="c1", delta='"Lisbon"}'),
    )
    assert _call(conv).args_text == '{"city": "Lisbon"}'
    assert _call(conv).args is None
    assert conv.dirty_tool_args == frozenset({"c1"})


def test_REQ_009_3_end_parses_args_and_sets_running() -> None:
    """REQ-009.3: END parses the args and hands the call to execution (``running``)."""
    conv = _apply(
        _started(),
        _start(),
        ToolCallArgsEvent(tool_call_id="c1", delta='{"city": "Lisbon"}'),
        ToolCallEndEvent(tool_call_id="c1"),
    )
    assert _call(conv).status is ToolCallStatus.RUNNING
    assert _call(conv).args == {"city": "Lisbon"}
    assert conv.dirty_tool_args == frozenset()


def test_REQ_009_3_end_with_no_args_means_an_empty_object() -> None:
    """REQ-009.3: a tool without arguments may send no ARGS at all."""
    conv = _apply(_started(), _start(), ToolCallEndEvent(tool_call_id="c1"))
    assert _call(conv).args == {}
    assert _call(conv).status is ToolCallStatus.RUNNING


def test_REQ_018_2_client_tool_stays_running_after_end() -> None:
    """REQ-018.2: a client-side tool is handed to its handler: ``running`` after END."""
    conv = _apply(_started(), _start("c1", "pick_date"), ToolCallEndEvent(tool_call_id="c1"))
    assert _call(conv).status is ToolCallStatus.RUNNING
    assert _call(conv).is_client_tool is True


def test_REQ_009_7_invalid_json_at_end_is_an_error_keeping_the_raw_text() -> None:
    """REQ-009.7: invalid args keep the raw text, set ``error`` and an explanatory result."""
    conv = _apply(
        _started(),
        _start(),
        ToolCallArgsEvent(tool_call_id="c1", delta='{"city": '),
        ToolCallEndEvent(tool_call_id="c1"),
    )
    call = _call(conv)
    assert call.status is ToolCallStatus.ERROR
    assert call.args_text == '{"city": '
    assert call.args is None
    assert call.result == INVALID_TOOL_ARGUMENTS


def test_REQ_009_7_args_that_are_not_an_object_are_invalid() -> None:
    """REQ-009.7, DM §3.2: tool arguments must be a JSON object."""
    conv = _apply(
        _started(),
        _start(),
        ToolCallArgsEvent(tool_call_id="c1", delta="[1, 2]"),
        ToolCallEndEvent(tool_call_id="c1"),
    )
    assert _call(conv).status is ToolCallStatus.ERROR


def test_REQ_009_2_args_over_the_cap_error_the_call() -> None:
    """DM §3.2: args beyond ``max_args_bytes`` put the call in ``error`` with a warning."""
    conv = _apply(
        _started(),
        _start(),
        ToolCallArgsEvent(tool_call_id="c1", delta='{"t": "' + "x" * 80 + '"}'),
        ToolCallArgsEvent(tool_call_id="c1", delta="more"),
        ToolCallEndEvent(tool_call_id="c1"),
    )
    call = _call(conv)
    assert call.status is ToolCallStatus.ERROR
    assert call.result is not None
    assert "64 bytes" in call.result
    assert _codes(conv) == [DiagnosticCode.ARGS_TOO_LARGE]
    assert conv.dirty_tool_args == frozenset()


# --- RESULT --------------------------------------------------------------------------------


def test_REQ_009_4_result_completes_the_call_and_appends_a_tool_message() -> None:
    """REQ-009.4: RESULT stores the content, sets ``done`` and appends a tool message."""
    conv = _apply(
        _started(),
        _start(),
        ToolCallEndEvent(tool_call_id="c1"),
        ToolCallResultEvent(tool_call_id="c1", message_id="t1", content="sunny"),
    )
    assert _call(conv).status is ToolCallStatus.DONE
    assert _call(conv).result == "sunny"
    tool_msg = conv.messages[-1]
    assert (tool_msg.id, tool_msg.role, tool_msg.tool_call_id, tool_msg.content) == (
        "t1",
        MessageRole.TOOL,
        "c1",
        "sunny",
    )


def test_REQ_009_4_result_message_is_deduplicated_by_message_id() -> None:
    """DM §7.1: a repeated RESULT with the same ``messageId`` appends no second message."""
    result = ToolCallResultEvent(tool_call_id="c1", message_id="t1", content="sunny")
    conv = _apply(_started(), _start(), ToolCallEndEvent(tool_call_id="c1"), result, result)
    assert [m.id for m in conv.messages].count("t1") == 1
    assert conv.diagnostics == ()


def test_REQ_009_4_result_ends_a_call_that_was_still_streaming() -> None:
    """REQ-009.5: a RESULT implies the call's args are complete."""
    conv = _apply(
        _started(),
        ToolCallChunkEvent(tool_call_id="c1", tool_call_name="t", delta='{"a": 1}'),
        ToolCallResultEvent(tool_call_id="c1", message_id="t1", content="ok"),
    )
    assert _call(conv).args == {"a": 1}
    assert _call(conv).status is ToolCallStatus.DONE


# --- unknown IDs ---------------------------------------------------------------------------


def test_REQ_009_6_events_for_unknown_calls_are_ignored_with_warnings() -> None:
    """REQ-009.6: ARGS/END/RESULT for an unknown ``toolCallId`` change nothing and warn."""
    before = _started()
    conv = _apply(
        before,
        ToolCallArgsEvent(tool_call_id="ghost", delta="{}"),
        ToolCallEndEvent(tool_call_id="ghost"),
        ToolCallResultEvent(tool_call_id="ghost", message_id="t1", content="x"),
    )
    assert conv.with_(diagnostics=()) == before
    assert _codes(conv) == [DiagnosticCode.UNKNOWN_TOOL_CALL_ID] * 3
    assert all(d.level == "warning" for d in conv.diagnostics)


def test_REQ_009_6_end_of_a_finished_call_changes_nothing() -> None:
    """REQ-009.3: END for a call that is no longer streaming is a no-op."""
    conv = _apply(_started(), _start(), ToolCallEndEvent(tool_call_id="c1"))
    assert reduce(conv, ToolCallEndEvent(tool_call_id="c1")) == conv


# --- CHUNK ---------------------------------------------------------------------------------


def test_REQ_009_5_chunks_start_feed_and_end_calls() -> None:
    """REQ-009.5: a new chunk ID starts a call and ends the previous chunk call."""
    conv = _apply(
        _started(),
        ToolCallChunkEvent(
            tool_call_id="c1", tool_call_name="a", parent_message_id="m1", delta="{"
        ),
        ToolCallChunkEvent(delta="}"),
        ToolCallChunkEvent(tool_call_id="c2", tool_call_name="b", parent_message_id="m1"),
    )
    assert _call(conv, "c1").status is ToolCallStatus.RUNNING
    assert _call(conv, "c1").args == {}
    assert _call(conv, "c2").status is ToolCallStatus.STREAMING
    assert conv.messages[conv._message_index["m1"]].tool_call_ids == ("c1", "c2")


def test_REQ_009_5_chunk_with_known_id_appends_args() -> None:
    """REQ-009.5: later chunks may repeat the call ID."""
    conv = _apply(
        _started(),
        ToolCallChunkEvent(tool_call_id="c1", tool_call_name="a", delta='{"x": '),
        ToolCallChunkEvent(tool_call_id="c1", delta="1}"),
    )
    assert _call(conv).args_text == '{"x": 1}'


def test_REQ_009_5_chunk_without_a_call_to_feed_is_a_warning() -> None:
    """REQ-009.5, REQ-009.6: an ID-less chunk with no open call, or a new ID without a
    name, is skipped with a warning."""
    conv = _apply(
        _started(),
        ToolCallChunkEvent(delta="{}"),
        ToolCallChunkEvent(tool_call_id="c9", delta="{}"),
    )
    assert conv.tool_calls == ()
    assert _codes(conv) == [DiagnosticCode.UNKNOWN_TOOL_CALL_ID] * 2


# --- run end -------------------------------------------------------------------------------


def test_REQ_009_5_run_finished_ends_calls_still_streaming() -> None:
    """REQ-009.5: chunk-fed calls have no END; the run's end completes them."""
    conv = _started()
    conv = _apply(
        conv,
        ToolCallChunkEvent(tool_call_id="c1", tool_call_name="a", delta='{"x": 1}'),
        RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id),
    )
    assert _call(conv).status is ToolCallStatus.RUNNING
    assert _call(conv).args == {"x": 1}


def test_REQ_004_3_run_error_fails_calls_still_streaming() -> None:
    """REQ-004.3, INV-5: a failed run leaves no call streaming."""
    conv = _apply(_started(), _start(), RunErrorEvent(message="boom"))
    assert _call(conv).status is ToolCallStatus.ERROR


def test_REQ_009_4_multimodal_result_is_flattened_to_text() -> None:
    """REQ-009.4, DM §7.1 v1.3: text parts are kept, other parts become placeholders."""
    result = ToolCallResultEvent.model_validate(
        {
            "toolCallId": "c1",
            "messageId": "t1",
            "content": [
                {"type": "text", "text": "Here: "},
                {"type": "image", "source": {"type": "url", "value": "https://x/y.png"}},
            ],
        }
    )
    conv = _apply(_started(), _start(), ToolCallEndEvent(tool_call_id="c1"), result)
    assert _call(conv).result == "Here: [image]"
    assert conv.messages[-1].content == "Here: [image]"


def test_REQ_009_5_id_less_chunk_continues_the_last_streaming_call() -> None:
    """REQ-009.5: an ID-less chunk skips finished calls and feeds the open one."""
    conv = _apply(
        _started(),
        _start("c1"),
        _start("c2"),
        ToolCallEndEvent(tool_call_id="c2"),
        ToolCallChunkEvent(delta="{}"),
    )
    assert _call(conv, "c1").args_text == "{}"
    assert _call(conv, "c2").args_text == ""


@pytest.mark.parametrize(
    "args_text",
    ["[" * 100_000 + "]" * 100_000, '{"x": NaN}', '{"x": Infinity}'],
    ids=["deeply-nested", "nan", "infinity"],
)
def test_REQ_009_7_pathological_args_are_invalid_not_a_crash(args_text: str) -> None:
    """REQ-005.1, REQ-009.7: ``reduce`` stays total on hostile args; they are invalid."""
    config = ReducerConfig(max_args_bytes=1_048_576)
    conv = _apply(
        _started(config),
        _start(),
        ToolCallArgsEvent(tool_call_id="c1", delta=args_text),
        ToolCallEndEvent(tool_call_id="c1"),
    )
    assert _call(conv).status is ToolCallStatus.ERROR
    assert _call(conv).result == INVALID_TOOL_ARGUMENTS
