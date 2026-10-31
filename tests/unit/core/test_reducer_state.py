"""Reducer: shared state, messages snapshot, CUSTOM and reasoning (T-013)."""

from __future__ import annotations

from typing import Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    MessagesSnapshotEvent,
    ReasoningEncryptedValueEvent,
    ReasoningEndEvent,
    ReasoningMessageChunkEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    CustomEventRecord,
    DiagnosticCode,
    MessageRole,
    ReasoningRecord,
    ReducerConfig,
    ToolCallStatus,
)
from reflex_agentkit.core.reducer import reduce

CONFIG = ReducerConfig(custom_events_limit=3)


def _started(config: ReducerConfig = CONFIG) -> ConversationState:
    conv = begin_run(ConversationState.initial(config), user_text="hi", config=config)
    return reduce(conv, RunStartedEvent(thread_id=conv.thread_id, run_id=conv.run_id))


def _apply(conv: ConversationState, *events: BaseEvent) -> ConversationState:
    for event in events:
        conv = reduce(conv, event)
    check_invariants(conv)
    return conv


def _codes(conv: ConversationState) -> list[DiagnosticCode]:
    return [d.code for d in conv.diagnostics]


def _delta(ops: list[dict[str, Any]]) -> StateDeltaEvent:
    return StateDeltaEvent.model_validate({"delta": ops})


def _snapshot(messages: list[dict[str, Any]]) -> MessagesSnapshotEvent:
    return MessagesSnapshotEvent.model_validate({"messages": messages})


# --- shared state --------------------------------------------------------------------------


def test_REQ_016_1_snapshot_replaces_shared_state() -> None:
    """REQ-016.1: ``STATE_SNAPSHOT`` replaces ``shared_state``."""
    conv = _apply(
        _started(),
        StateSnapshotEvent(snapshot={"a": 1}),
        StateSnapshotEvent(snapshot={"b": [1, 2]}),
    )
    assert conv.shared_state == {"b": [1, 2]}


def test_REQ_016_1_snapshot_is_copied_from_the_event() -> None:
    """DM R-2: later mutation of the event's payload cannot reach the state."""
    payload: dict[str, Any] = {"items": [1]}
    conv = _apply(_started(), StateSnapshotEvent(snapshot=payload))
    payload["items"].append(2)
    assert conv.shared_state == {"items": [1]}


def test_REQ_016_2_delta_applies_rfc6902_ops() -> None:
    """REQ-016.2: ``STATE_DELTA`` applies its operations atomically."""
    conv = _apply(
        _started(),
        StateSnapshotEvent(snapshot={"count": 1, "tags": []}),
        _delta(
            [
                {"op": "replace", "path": "/count", "value": 2},
                {"op": "add", "path": "/tags/-", "value": "x"},
            ]
        ),
    )
    assert conv.shared_state == {"count": 2, "tags": ["x"]}
    assert conv.shared_state_stale is False


def test_REQ_016_3_failed_delta_leaves_state_marks_stale_and_warns() -> None:
    """REQ-016.3: a failing delta changes nothing, sets stale, warns, and the run goes on."""
    before = _apply(_started(), StateSnapshotEvent(snapshot={"count": 1}))
    conv = _apply(
        before,
        _delta(
            [
                {"op": "replace", "path": "/count", "value": 9},
                {"op": "remove", "path": "/missing"},
            ]
        ),
    )
    assert conv.shared_state == {"count": 1}
    assert conv.shared_state_stale is True
    assert conv.error_code is ErrorCode.SHARED_STATE_PATCH_FAILED
    assert conv.run_status is before.run_status
    assert _codes(conv) == [DiagnosticCode.PATCH_FAILED]
    assert conv.diagnostics[0].level == "warning"


def test_REQ_016_4_later_snapshot_clears_stale() -> None:
    """REQ-016.4: a later snapshot clears ``shared_state_stale``."""
    conv = _apply(
        _started(),
        _delta([{"op": "remove", "path": "/missing"}]),
        StateSnapshotEvent(snapshot={"fresh": True}),
    )
    assert conv.shared_state == {"fresh": True}
    assert conv.shared_state_stale is False


def test_REQ_016_5_snapshot_that_is_not_an_object_is_rejected() -> None:
    """REQ-016.5, INV-10: ``shared_state`` stays a JSON object; a bad snapshot is stale."""
    conv = _apply(
        _apply(_started(), StateSnapshotEvent(snapshot={"a": 1})),
        StateSnapshotEvent(snapshot=[1, 2, 3]),
    )
    assert conv.shared_state == {"a": 1}
    assert conv.shared_state_stale is True
    assert conv.error_code is ErrorCode.SHARED_STATE_INVALID
    assert _codes(conv) == [DiagnosticCode.INVALID_EVENT]


# --- CUSTOM --------------------------------------------------------------------------------


def test_REQ_010_5_custom_events_form_a_bounded_ring() -> None:
    """REQ-010.5, INV-9: ``CUSTOM`` appends ``{name, value}``; only the latest N are kept."""
    conv = _started()
    conv = _apply(conv, *(CustomEvent(name="n", value=i) for i in range(5)))
    assert conv.custom_events == tuple(
        CustomEventRecord(name="n", value=i, run_id=conv.run_id) for i in (2, 3, 4)
    )


def test_REQ_010_5_a_zero_limit_keeps_no_custom_events() -> None:
    """REQ-010.5: ``custom_events_limit = 0`` disables the ring."""
    conv = _apply(_started(ReducerConfig(custom_events_limit=0)), CustomEvent(name="n", value=1))
    assert conv.custom_events == ()


# --- MESSAGES_SNAPSHOT ---------------------------------------------------------------------


def test_REQ_010_4_snapshot_replaces_messages_and_keeps_surviving_call_statuses() -> None:
    """REQ-010.4: messages are replaced; calls still present keep their status."""
    conv = _apply(
        _started(),
        ToolCallStartEvent(tool_call_id="c1", tool_call_name="t", parent_message_id="a1"),
        ToolCallEndEvent(tool_call_id="c1"),
        ToolCallStartEvent(tool_call_id="gone", tool_call_name="t", parent_message_id="a1"),
        _snapshot(
            [
                {"id": "u1", "role": "user", "content": "hi"},
                {
                    "id": "a1",
                    "role": "assistant",
                    "toolCalls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "t", "arguments": "{}"},
                        }
                    ],
                },
            ]
        ),
    )
    assert [m.id for m in conv.messages] == ["u1", "a1"]
    assert [c.id for c in conv.tool_calls] == ["c1"]
    assert conv.tool_calls[0].status is ToolCallStatus.RUNNING
    assert conv.dirty_tool_args == frozenset()


def test_REQ_010_4_snapshot_creates_records_for_new_calls() -> None:
    """REQ-010.4, INV-3: calls known only from the snapshot get records."""
    conv = _apply(
        _started(),
        _snapshot(
            [
                {
                    "id": "a1",
                    "role": "assistant",
                    "content": "Let me check",
                    "toolCalls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"q": 1}'},
                        },
                        {
                            "id": "c2",
                            "type": "function",
                            "function": {"name": "x", "arguments": "{"},
                        },
                    ],
                },
                {"id": "t1", "role": "tool", "toolCallId": "c1", "content": "found", "error": ""},
            ]
        ),
    )
    c1, c2 = conv.tool_calls
    assert (c1.name, c1.args, c1.status, c1.result, c1.parent_message_id) == (
        "lookup",
        {"q": 1},
        ToolCallStatus.DONE,
        "found",
        "a1",
    )
    assert c2.status is ToolCallStatus.ERROR
    assert conv.messages[0].tool_call_ids == ("c1", "c2")


def test_REQ_010_4_snapshot_maps_roles_content_and_tool_errors() -> None:
    """DM §7.1: every AG-UI role maps; user content parts flatten; tool errors flag."""
    conv = _apply(
        _started(),
        _snapshot(
            [
                {"id": "s", "role": "system", "content": "sys"},
                {"id": "d", "role": "developer", "content": "dev"},
                {
                    "id": "u",
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look "},
                        {"type": "image", "source": {"type": "url", "value": "https://x/i.png"}},
                    ],
                },
                {
                    "id": "a",
                    "role": "assistant",
                    "toolCalls": [
                        {"id": "c", "type": "function", "function": {"name": "t", "arguments": ""}}
                    ],
                },
                {"id": "t", "role": "tool", "toolCallId": "c", "content": "x", "error": "failed"},
                {"id": "act", "role": "activity", "activityType": "plan", "content": {}},
            ]
        ),
    )
    roles = [(m.id, m.role) for m in conv.messages]
    assert roles == [
        ("s", MessageRole.SYSTEM),
        ("d", MessageRole.DEVELOPER),
        ("u", MessageRole.USER),
        ("a", MessageRole.ASSISTANT),
        ("t", MessageRole.TOOL),
    ]
    assert conv.messages[2].content == "look [image]"
    assert conv.messages[4].is_error is True
    assert conv.tool_calls[0].status is ToolCallStatus.ERROR


def test_REQ_010_4_snapshot_drops_orphan_tool_messages_and_duplicates() -> None:
    """INV-1, INV-3: orphan tool messages and repeated IDs are dropped with warnings."""
    conv = _apply(
        _started(),
        _snapshot(
            [
                {"id": "u1", "role": "user", "content": "a"},
                {"id": "u1", "role": "user", "content": "b"},
                {"id": "t1", "role": "tool", "toolCallId": "nobody", "content": "x"},
            ]
        ),
    )
    assert [(m.id, m.content) for m in conv.messages] == [("u1", "a")]
    assert _codes(conv) == [DiagnosticCode.DUPLICATE_ID, DiagnosticCode.UNKNOWN_TOOL_CALL_ID]


def test_REQ_011_snapshot_reasoning_messages_become_records() -> None:
    """REQ-011, DM §3.6: reasoning messages link to the following assistant message."""
    conv = _apply(
        _started(),
        _snapshot(
            [
                {"id": "r1", "role": "reasoning", "content": "hmm", "encryptedValue": "sig"},
                {"id": "a1", "role": "assistant", "content": "ok"},
                {"id": "r2", "role": "reasoning", "content": "after"},
            ]
        ),
    )
    assert [m.id for m in conv.messages] == ["a1"]
    assert conv.reasoning == (
        ReasoningRecord(id="r1", assistant_message_id="a1", content="hmm", encrypted_value="sig"),
        ReasoningRecord(id="r2", assistant_message_id="a1", content="after"),
    )


def test_REQ_011_2_snapshot_keeps_streamed_reasoning_of_surviving_messages() -> None:
    """REQ-011.2: a snapshot without reasoning messages keeps the encrypted values we hold."""
    conv = _apply(
        _started(),
        ReasoningMessageStartEvent(message_id="r1", role="reasoning"),
        ReasoningEncryptedValueEvent(subtype="message", entity_id="r1", encrypted_value="sig"),
        TextMessageStartEvent(message_id="a1"),
        ReasoningMessageStartEvent(message_id="r2", role="reasoning"),
        TextMessageStartEvent(message_id="a2"),
        _snapshot([{"id": "a1", "role": "assistant", "content": "x"}]),
    )
    assert [r.id for r in conv.reasoning] == ["r1"]
    assert conv.reasoning[0].encrypted_value == "sig"


# --- reasoning streams ---------------------------------------------------------------------


def test_REQ_011_1_reasoning_accumulates_and_links_to_the_next_assistant_message() -> None:
    """REQ-011.1, DM §3.6: text accumulates; the turn's next assistant message owns it."""
    conv = _apply(
        _started(),
        ReasoningStartEvent(message_id="r1"),
        ReasoningMessageStartEvent(message_id="r1", role="reasoning"),
        ReasoningMessageContentEvent(message_id="r1", delta="a"),
        ReasoningMessageContentEvent(message_id="r1", delta="b"),
        ReasoningMessageEndEvent(message_id="r1"),
        ReasoningEndEvent(message_id="r1"),
        TextMessageStartEvent(message_id="m1"),
    )
    assert conv.reasoning == (ReasoningRecord(id="r1", assistant_message_id="m1", content="ab"),)
    assert conv.messages[-1].reasoning == ""


def test_REQ_011_1_reasoning_after_the_last_text_links_to_the_previous_message() -> None:
    """DM §3.6: with no following assistant message, the previous one owns the reasoning."""
    conv = _started()
    conv = _apply(
        conv,
        TextMessageStartEvent(message_id="m1"),
        ReasoningMessageChunkEvent(message_id="r1", delta="late"),
        RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id),
    )
    assert conv.reasoning[0].assistant_message_id == "m1"


def test_REQ_011_1_reasoning_also_links_on_run_error() -> None:
    """DM §3.6: linking at run end also happens when the run fails."""
    conv = _apply(
        _started(),
        TextMessageStartEvent(message_id="m1"),
        ReasoningMessageStartEvent(message_id="r1", role="reasoning"),
        RunErrorEvent(message="boom"),
    )
    assert conv.reasoning[0].assistant_message_id == "m1"


def test_REQ_011_1_reasoning_links_to_a_tool_call_parent_message() -> None:
    """DM §3.6: an assistant message created for a tool call also owns the reasoning."""
    conv = _apply(
        _started(),
        ReasoningMessageStartEvent(message_id="r1", role="reasoning"),
        ToolCallStartEvent(tool_call_id="c1", tool_call_name="t", parent_message_id="a1"),
    )
    assert conv.reasoning[0].assistant_message_id == "a1"


def test_REQ_011_1_reasoning_chunks_start_and_continue_records() -> None:
    """REQ-011.1: chunks follow the text-chunk rules."""
    conv = _apply(
        _started(),
        ReasoningMessageChunkEvent(message_id="r1", delta="a"),
        ReasoningMessageChunkEvent(delta="b"),
        ReasoningMessageChunkEvent(message_id="r1", delta="c"),
        ReasoningMessageChunkEvent(message_id="r2"),
    )
    assert [(r.id, r.content) for r in conv.reasoning] == [("r1", "abc"), ("r2", "")]


def test_REQ_011_1_reasoning_without_a_target_is_a_warning() -> None:
    """REQ-011.1: an ID-less chunk with no record yet, or END of an unknown ID, warns."""
    conv = _apply(
        _started(),
        ReasoningMessageChunkEvent(delta="orphan"),
        ReasoningMessageEndEvent(message_id="ghost"),
    )
    assert conv.reasoning == ()
    assert _codes(conv) == [DiagnosticCode.UNKNOWN_MESSAGE_ID] * 2


def test_REQ_011_1_reasoning_content_for_an_unknown_id_creates_the_record() -> None:
    """REQ-011.1, REQ-008.5 analogue: content before start creates the record and warns."""
    conv = _apply(_started(), ReasoningMessageContentEvent(message_id="r1", delta="x"))
    assert conv.reasoning == (ReasoningRecord(id="r1", content="x"),)
    assert _codes(conv) == [DiagnosticCode.IMPLICIT_MESSAGE]


def test_REQ_011_1_duplicate_reasoning_start_is_a_warning() -> None:
    """INV-1: a second start of the same reasoning ID keeps one record."""
    conv = _apply(
        _started(),
        ReasoningMessageStartEvent(message_id="r1", role="reasoning"),
        ReasoningMessageStartEvent(message_id="r1", role="reasoning"),
    )
    assert len(conv.reasoning) == 1
    assert _codes(conv) == [DiagnosticCode.DUPLICATE_ID]


def test_REQ_011_2_encrypted_value_is_kept_on_its_reasoning_record() -> None:
    """REQ-011.2, INV-11: the opaque value is stored server-side, never in a message."""
    conv = _apply(
        _started(),
        ReasoningMessageStartEvent(message_id="r1", role="reasoning"),
        ReasoningEncryptedValueEvent(subtype="message", entity_id="r1", encrypted_value="sig"),
        TextMessageStartEvent(message_id="m1"),
    )
    assert conv.reasoning[0].encrypted_value == "sig"
    assert all("sig" not in (m.content + m.reasoning) for m in conv.messages)


def test_REQ_011_2_encrypted_value_for_another_entity_is_not_retained() -> None:
    """DM §7.1 v1.4: values for tool calls or non-reasoning messages are dropped (debug)."""
    before = _started()
    conv = _apply(
        before,
        ReasoningEncryptedValueEvent(subtype="tool-call", entity_id="c1", encrypted_value="x"),
        ReasoningEncryptedValueEvent(subtype="message", entity_id="u?", encrypted_value="y"),
    )
    assert conv.with_(diagnostics=()) == before
    assert _codes(conv) == [DiagnosticCode.IGNORED_EVENT] * 2
    assert all(d.level == "debug" for d in conv.diagnostics)


def test_REQ_011_1_reasoning_with_no_assistant_message_stays_unlinked() -> None:
    """DM §3.6: with no assistant message at all, the record has no owner."""
    conv = _started()
    conv = _apply(
        conv,
        ReasoningMessageStartEvent(message_id="r1", role="reasoning"),
        RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id),
    )
    assert conv.reasoning[0].assistant_message_id is None


def test_REQ_016_5_pathologically_deep_snapshot_is_invalid_not_a_crash() -> None:
    """REQ-005.1: a snapshot too deep to copy is rejected like a non-object snapshot."""
    deep: dict[str, Any] = {}
    node = deep
    for _ in range(100_000):
        node["n"] = {}
        node = node["n"]
    conv = reduce(_started(), StateSnapshotEvent(snapshot=deep))
    assert conv.shared_state == {}
    assert conv.shared_state_stale is True
    assert _codes(conv) == [DiagnosticCode.INVALID_EVENT]


def test_REQ_010_4_snapshot_lists_each_tool_call_once() -> None:
    """INV-1: a call listed twice in the snapshot gets one record."""
    call = {"id": "c1", "type": "function", "function": {"name": "t", "arguments": "{}"}}
    conv = _apply(
        _started(),
        _snapshot([{"id": "a1", "role": "assistant", "toolCalls": [call, call]}]),
    )
    assert [c.id for c in conv.tool_calls] == ["c1"]
    assert conv.messages[0].tool_call_ids == ("c1",)
