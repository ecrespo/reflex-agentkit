"""Reducer: text messages (T-011, REQ-008)."""

from __future__ import annotations

from ag_ui.core import (
    BaseEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageChunkEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import ChatMessage, DiagnosticCode, MessageRole, ReducerConfig
from reflex_agentkit.core.reducer import reduce

CONFIG = ReducerConfig()


def _started() -> ConversationState:
    conv = begin_run(ConversationState.initial(CONFIG), user_text="hi", config=CONFIG)
    return reduce(conv, RunStartedEvent(thread_id=conv.thread_id, run_id=conv.run_id))


def _apply(conv: ConversationState, *events: BaseEvent) -> ConversationState:
    for event in events:
        conv = reduce(conv, event)
    return conv


def _last(conv: ConversationState) -> ChatMessage:
    return conv.messages[-1]


def _codes(conv: ConversationState) -> list[DiagnosticCode]:
    return [d.code for d in conv.diagnostics]


def test_REQ_008_1_start_appends_a_streaming_assistant_message() -> None:
    """REQ-008.1: START appends an assistant message, empty and streaming."""
    conv = _apply(_started(), TextMessageStartEvent(message_id="m1"))
    assert _last(conv) == ChatMessage(id="m1", role=MessageRole.ASSISTANT, streaming=True)
    assert conv._message_index["m1"] == 1


def test_REQ_008_1_start_keeps_an_explicit_role() -> None:
    """REQ-008.1: an explicit AG-UI role on START is kept (assistant is the default)."""
    conv = _apply(_started(), TextMessageStartEvent(message_id="s1", role="system"))
    assert _last(conv).role is MessageRole.SYSTEM


def test_REQ_008_2_content_appends_the_delta() -> None:
    """REQ-008.2: CONTENT appends its delta to the known message."""
    conv = _apply(
        _started(),
        TextMessageStartEvent(message_id="m1"),
        TextMessageContentEvent(message_id="m1", delta="Hel"),
        TextMessageContentEvent(message_id="m1", delta="lo"),
    )
    assert _last(conv).content == "Hello"
    assert conv.diagnostics == ()


def test_REQ_008_3_end_stops_streaming() -> None:
    """REQ-008.3: END sets ``streaming = false``."""
    conv = _apply(
        _started(),
        TextMessageStartEvent(message_id="m1"),
        TextMessageContentEvent(message_id="m1", delta="x"),
        TextMessageEndEvent(message_id="m1"),
    )
    assert _last(conv).streaming is False
    assert _last(conv).content == "x"


def test_REQ_008_3_duplicate_start_is_a_warning() -> None:
    """REQ-008.3, INV-1: a second START for the same ID keeps one message and warns."""
    conv = _apply(
        _started(),
        TextMessageStartEvent(message_id="m1"),
        TextMessageContentEvent(message_id="m1", delta="x"),
        TextMessageStartEvent(message_id="m1"),
    )
    assert [m.id for m in conv.messages].count("m1") == 1
    assert _last(conv).content == "x"
    assert _codes(conv) == [DiagnosticCode.DUPLICATE_ID]
    check_invariants(conv)


def test_REQ_008_4_chunks_start_continue_and_switch_messages() -> None:
    """REQ-008.4: the first chunk of an ID starts it; later chunks (ID optional) append."""
    conv = _apply(
        _started(),
        TextMessageChunkEvent(message_id="m1", delta="a"),
        TextMessageChunkEvent(delta="b"),
        TextMessageChunkEvent(message_id="m1", delta="c"),
        TextMessageChunkEvent(message_id="m2", delta="d"),
    )
    assert [(m.id, m.content, m.streaming) for m in conv.messages[1:]] == [
        ("m1", "abc", False),
        ("m2", "d", True),
    ]
    assert conv.diagnostics == ()


def test_REQ_008_4_chunk_without_id_and_no_open_message_is_skipped() -> None:
    """REQ-008.4: a chunk that names no message and has none to continue is a warning."""
    conv = _apply(_started(), TextMessageChunkEvent(delta="orphan"))
    assert len(conv.messages) == 1
    assert _codes(conv) == [DiagnosticCode.UNKNOWN_MESSAGE_ID]


def test_REQ_008_4_chunks_close_at_run_end() -> None:
    """REQ-008.4: the chunk stream's implicit END happens when the run ends."""
    conv = _started()
    conv = _apply(
        conv,
        TextMessageChunkEvent(message_id="m1", delta="a"),
        RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id),
    )
    assert _last(conv).streaming is False
    check_invariants(conv)


def test_REQ_008_5_content_for_an_unknown_id_creates_the_message() -> None:
    """REQ-008.5: CONTENT for an unknown ID creates the message and warns."""
    conv = _apply(_started(), TextMessageContentEvent(message_id="ghost", delta="boo"))
    assert _last(conv) == ChatMessage(
        id="ghost", role=MessageRole.ASSISTANT, content="boo", streaming=True
    )
    assert _codes(conv) == [DiagnosticCode.IMPLICIT_MESSAGE]
    assert conv.diagnostics[0].level == "warning"


def test_REQ_008_5_end_for_an_unknown_id_is_a_warning() -> None:
    """REQ-008.5: END for an unknown ID changes nothing and warns."""
    before = _started()
    conv = _apply(before, TextMessageEndEvent(message_id="ghost"))
    assert conv.messages == before.messages
    assert _codes(conv) == [DiagnosticCode.UNKNOWN_MESSAGE_ID]


def test_REQ_008_6_run_end_closes_open_messages() -> None:
    """REQ-008.6: messages still streaming when the run ends stop streaming."""
    for terminal in ("finished", "error"):
        conv = _apply(
            _started(),
            TextMessageStartEvent(message_id="m1"),
            TextMessageContentEvent(message_id="m1", delta="partial"),
        )
        end: BaseEvent = (
            RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id)
            if terminal == "finished"
            else RunErrorEvent(message="boom")
        )
        conv = reduce(conv, end)
        assert _last(conv).streaming is False
        assert _last(conv).content == "partial"
        check_invariants(conv)


def test_REQ_008_6_events_after_the_run_ended_are_ignored() -> None:
    """REQ-008.6, INV-5: content arriving after the run ended cannot reopen a stream."""
    conv = _started()
    conv = reduce(conv, RunFinishedEvent(thread_id=conv.thread_id, run_id=conv.run_id))
    after = _apply(conv, TextMessageContentEvent(message_id="late", delta="x"))
    assert after.messages == conv.messages
    assert _codes(after) == [DiagnosticCode.IGNORED_EVENT]
    check_invariants(after)


def test_REQ_008_3_a_repeated_end_changes_nothing() -> None:
    """REQ-008.3: ending an already-ended message is a no-op."""
    conv = _apply(
        _started(), TextMessageStartEvent(message_id="m1"), TextMessageEndEvent(message_id="m1")
    )
    assert reduce(conv, TextMessageEndEvent(message_id="m1")) == conv
