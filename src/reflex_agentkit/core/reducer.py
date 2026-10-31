"""The pure AG-UI event reducer: ``reduce(state, event) -> state`` (API §11, REQ-005).

``reduce`` is the only path by which agent events change a conversation. It does no
I/O, reads no clock and uses no randomness. It is total: an event it cannot apply
becomes a :class:`Diagnostic` on the returned state instead of an exception. The state
layer logs those diagnostics and clears them.

Dispatch is a table keyed by ``EventType``. Types without a handler (a future protocol
addition) fall through to an ``UNKNOWN_EVENT_TYPE`` debug diagnostic (REQ-012.2), so a
new upstream type never needs a code change to stay safe.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Callable, Mapping
from typing import Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    Event,
    EventType,
    MessagesSnapshotEvent,
    ReasoningEncryptedValueEvent,
    ReasoningMessageChunkEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    TextMessageChunkEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallChunkEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from pydantic import TypeAdapter, ValidationError

from reflex_agentkit.core._patch import PatchError, apply_patch
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    CustomEventRecord,
    Diagnostic,
    DiagnosticCode,
    DiagnosticLevel,
    JsonObject,
    MessageRole,
    OpenInterrupt,
    ReasoningRecord,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)

__all__ = [
    "HANDLED_EVENT_TYPES",
    "INCOMPLETE_TOOL_CALL",
    "INVALID_TOOL_ARGUMENTS",
    "close_streams",
    "parse_event",
    "reduce",
]

Handler = Callable[[ConversationState, Any], ConversationState]

_EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(Event)
_KNOWN_TYPES = frozenset(member.value for member in EventType)

INCOMPLETE_TOOL_CALL = "The run ended before the tool call's arguments were complete."
INVALID_TOOL_ARGUMENTS = "Invalid tool arguments: the arguments are not a valid JSON object."

# REQ-012.1: accepted, never rendered in v0.1.
_IGNORED: frozenset[str] = frozenset(
    {
        EventType.ACTIVITY_SNAPSHOT,
        EventType.ACTIVITY_DELTA,
        EventType.SUBAGENT_STARTED,
        EventType.SUBAGENT_FINISHED,
        EventType.SUBAGENT_ERROR,
        EventType.RAW,
    }
)


# --- helpers -------------------------------------------------------------------------------


def _type_name(event_type: object) -> str:
    return str(getattr(event_type, "value", event_type))


def _diag(
    conv: ConversationState,
    level: DiagnosticLevel,
    code: DiagnosticCode,
    message: str,
    event_type: str | None,
) -> ConversationState:
    diagnostic = Diagnostic(level=level, code=code, message=message, event_type=event_type)
    return conv.with_(diagnostics=(*conv.diagnostics, diagnostic))


def close_streams(conv: ConversationState, *, finished: bool) -> ConversationState:
    """End every open stream when the run ends (REQ-008.6, REQ-009.5, INV-5).

    On ``RUN_FINISHED`` a call still streaming gets its implicit END (chunk-fed calls
    have no explicit one). On ``RUN_ERROR`` it fails as incomplete.
    """
    changes: dict[str, Any] = {}
    if any(m.streaming for m in conv.messages):
        changes["messages"] = tuple(
            dataclasses.replace(m, streaming=False) if m.streaming else m for m in conv.messages
        )
    if any(c.status is ToolCallStatus.STREAMING for c in conv.tool_calls):
        changes["tool_calls"] = tuple(
            (
                _end_call(c)
                if finished
                else dataclasses.replace(
                    c, status=ToolCallStatus.ERROR, result=INCOMPLETE_TOOL_CALL
                )
            )
            if c.status is ToolCallStatus.STREAMING
            else c
            for c in conv.tool_calls
        )
        changes["dirty_tool_args"] = frozenset()
    if any(r.assistant_message_id is None for r in conv.reasoning):
        # DM §3.6: reasoning with no following assistant message joins the previous one.
        last = _last_assistant_id(conv.messages)
        if last is not None:
            changes["reasoning"] = _link_reasoning(conv.reasoning, last)
    return conv.with_(**changes) if changes else conv


def _last_assistant_id(messages: tuple[ChatMessage, ...]) -> str | None:
    for msg in reversed(messages):
        if msg.role is MessageRole.ASSISTANT:
            return msg.id
    return None


def _link_reasoning(
    records: tuple[ReasoningRecord, ...], assistant_id: str
) -> tuple[ReasoningRecord, ...]:
    """Attach every not-yet-linked reasoning record to ``assistant_id`` (DM §3.6)."""
    return tuple(
        dataclasses.replace(r, assistant_message_id=assistant_id)
        if r.assistant_message_id is None
        else r
        for r in records
    )


def _stale(conv: ConversationState, run_id: str, event_type: str) -> ConversationState:
    return _diag(
        conv,
        "warning",
        DiagnosticCode.STALE_RUN_EVENT,
        f"discarded {event_type} of run {run_id!r}, which is not part of the current turn",
        event_type,
    )


def _after_end(conv: ConversationState, event_type: str) -> ConversationState:
    return _diag(
        conv,
        "debug",
        DiagnosticCode.IGNORED_EVENT,
        f"ignored {event_type}: the run is not running (status {conv.run_status.value!r})",
        event_type,
    )


# --- lifecycle -----------------------------------------------------------------------------


def _run_started(conv: ConversationState, event: RunStartedEvent) -> ConversationState:
    """REQ-010.1-2: accept runs of the current turn; discard any other run.

    ``begin_run`` already recorded the active ``run_id``. A late ``RUN_STARTED`` of an
    earlier run of the same turn must not move it back: the driver's ownership check
    compares ``run_id`` with the run it is streaming (TD Flow A.7).
    """
    if event.run_id not in conv.last_run_ids:
        return _stale(conv, event.run_id, EventType.RUN_STARTED.value)
    return conv


def _interrupt_payload(metadata: object) -> Any:
    """DM §3.4: LangGraph carries the ``interrupt(value)`` argument in its metadata."""
    if isinstance(metadata, dict):
        langgraph = metadata.get("langgraph")
        if isinstance(langgraph, dict):
            return langgraph.get("raw")
    return None


def _pause(conv: ConversationState, interrupts: list[Any]) -> ConversationState:
    """REQ-004.2, REQ-013.1, REQ-014.1/3: store the interrupts in arrival order.

    An interrupt is an approval exactly when it names a known tool call; that call goes
    to ``pending_approval``. A ``tool_call`` interrupt naming an unknown call is kept as a
    generic one (``tool_call_id=None``) so it can still be answered (DM §7.2 v1.5).
    """
    event_type = EventType.RUN_FINISHED.value
    opened: list[OpenInterrupt] = []
    for interrupt in interrupts:
        if any(o.id == interrupt.id for o in opened):
            conv = _diag(
                conv,
                "warning",
                DiagnosticCode.DUPLICATE_ID,
                f"dropped repeated interrupt {interrupt.id!r}",
                event_type,
            )
            continue
        call_id = interrupt.tool_call_id
        if call_id is not None and call_id not in conv._tool_index:
            conv = _diag(
                conv,
                "warning",
                DiagnosticCode.UNKNOWN_TOOL_CALL_ID,
                f"interrupt {interrupt.id!r} names unknown tool call {call_id!r};"
                " it is presented as a generic interrupt",
                event_type,
            )
            call_id = None
        opened.append(
            OpenInterrupt(
                id=interrupt.id,
                reason=interrupt.reason or "",
                message=interrupt.message or "",
                tool_call_id=call_id,
                payload=_interrupt_payload(interrupt.metadata),
                response_schema=interrupt.response_schema,
            )
        )
        if call_id is not None:
            call = conv.tool_calls[conv._tool_index[call_id]]
            pending = dataclasses.replace(
                call, status=ToolCallStatus.PENDING_APPROVAL, interrupt_id=interrupt.id
            )
            conv = _replace_call(conv, pending)
    if not opened:
        return conv.with_(run_status=RunStatus.IDLE)
    return conv.with_(interrupts=tuple(opened), answers={}, run_status=RunStatus.AWAITING_INPUT)


def _awaits_client_tools(conv: ConversationState, pending_ids: list[str] | None) -> bool:
    """REQ-004.1, A-18: client-tool calls handed off at END, or listed as pending."""
    if any(c.is_client_tool and c.status is ToolCallStatus.RUNNING for c in conv.tool_calls):
        return True
    return any(call_id in conv._tool_index for call_id in pending_ids or ())


def _run_finished(conv: ConversationState, event: RunFinishedEvent) -> ConversationState:
    """REQ-004.1-2, API §8.3: end the run according to its outcome."""
    if event.run_id not in conv.last_run_ids:
        return _stale(conv, event.run_id, EventType.RUN_FINISHED.value)
    outcome = event.outcome
    outcome_type = getattr(outcome, "type", "success")
    if outcome_type == "cancelled":
        return close_streams(conv, finished=False).with_(run_status=RunStatus.CANCELLED)
    conv = close_streams(conv, finished=True)
    if outcome_type == "interrupt":
        return _pause(conv, list(getattr(outcome, "interrupts", None) or []))
    if _awaits_client_tools(conv, getattr(outcome, "pending_tool_call_ids", None)):
        return conv  # the client-tool round keeps the run running (REQ-018.2)
    return conv.with_(run_status=RunStatus.IDLE)


def _run_error(conv: ConversationState, event: RunErrorEvent) -> ConversationState:
    """REQ-004.3: the run failed; the content streamed so far is kept."""
    return close_streams(conv, finished=False).with_(
        run_status=RunStatus.ERROR, error=event.message, error_code=ErrorCode.AGENT_RUN_ERROR
    )


def _step_started(conv: ConversationState, event: StepStartedEvent) -> ConversationState:
    """REQ-010.3: expose the step name."""
    return conv.with_(current_step=event.step_name)


def _step_finished(conv: ConversationState, event: StepFinishedEvent) -> ConversationState:
    """REQ-010.3: clear ``current_step`` when *that* step finishes."""
    if conv.current_step != event.step_name:
        return conv
    return conv.with_(current_step="")


# --- text messages -------------------------------------------------------------------------


def _replace_message(conv: ConversationState, index: int, msg: ChatMessage) -> ConversationState:
    return conv.with_(messages=(*conv.messages[:index], msg, *conv.messages[index + 1 :]))


def _append_message(conv: ConversationState, msg: ChatMessage) -> ConversationState:
    """Append a message; a new assistant message owns the turn's pending reasoning."""
    if msg.role is MessageRole.ASSISTANT and any(
        r.assistant_message_id is None for r in conv.reasoning
    ):
        return conv.with_(
            messages=(*conv.messages, msg), reasoning=_link_reasoning(conv.reasoning, msg.id)
        )
    return conv.with_(messages=(*conv.messages, msg))


def _role(role: str | None) -> MessageRole:
    return MessageRole(role) if role else MessageRole.ASSISTANT


def _append_delta(conv: ConversationState, index: int, delta: str) -> ConversationState:
    msg = conv.messages[index]
    return _replace_message(conv, index, dataclasses.replace(msg, content=msg.content + delta))


def _text_start(conv: ConversationState, event: TextMessageStartEvent) -> ConversationState:
    """REQ-008.1: append a streaming message (assistant unless the event names a role)."""
    if event.message_id in conv._message_index:
        return _diag(
            conv,
            "warning",
            DiagnosticCode.DUPLICATE_ID,
            f"ignored a second start of message {event.message_id!r}",
            EventType.TEXT_MESSAGE_START.value,
        )
    msg = ChatMessage(id=event.message_id, role=_role(event.role), streaming=True)
    return _append_message(conv, msg)


def _text_content(conv: ConversationState, event: TextMessageContentEvent) -> ConversationState:
    """REQ-008.2, REQ-008.5: append the delta, creating the message if it is unknown."""
    index = conv._message_index.get(event.message_id)
    if index is not None:
        return _append_delta(conv, index, event.delta)
    msg = ChatMessage(
        id=event.message_id, role=MessageRole.ASSISTANT, content=event.delta, streaming=True
    )
    return _diag(
        _append_message(conv, msg),
        "warning",
        DiagnosticCode.IMPLICIT_MESSAGE,
        f"created message {event.message_id!r} implicitly: content arrived before its start",
        EventType.TEXT_MESSAGE_CONTENT.value,
    )


def _text_end(conv: ConversationState, event: TextMessageEndEvent) -> ConversationState:
    """REQ-008.3: stop streaming the message."""
    index = conv._message_index.get(event.message_id)
    if index is None:
        return _diag(
            conv,
            "warning",
            DiagnosticCode.UNKNOWN_MESSAGE_ID,
            f"ignored the end of unknown message {event.message_id!r}",
            EventType.TEXT_MESSAGE_END.value,
        )
    msg = conv.messages[index]
    if not msg.streaming:
        return conv
    return _replace_message(conv, index, dataclasses.replace(msg, streaming=False))


def _open_message_index(conv: ConversationState) -> int | None:
    """The message a chunk without an ID continues: the last one still streaming."""
    for index in range(len(conv.messages) - 1, -1, -1):
        if conv.messages[index].streaming:
            return index
    return None


def _text_chunk(conv: ConversationState, event: TextMessageChunkEvent) -> ConversationState:
    """REQ-008.4: chunks are START (first chunk of an ID) + CONTENT; END comes at run end.

    A chunk that starts a new message ends the message chunks were feeding until then,
    as the AG-UI chunk semantics require. A chunk without an ID continues that message.
    """
    delta = event.delta or ""
    if event.message_id is None:
        index = _open_message_index(conv)
        if index is None:
            return _diag(
                conv,
                "warning",
                DiagnosticCode.UNKNOWN_MESSAGE_ID,
                "ignored a text chunk without a message ID and no message to continue",
                EventType.TEXT_MESSAGE_CHUNK.value,
            )
        return _append_delta(conv, index, delta) if delta else conv

    index = conv._message_index.get(event.message_id)
    if index is not None:
        return _append_delta(conv, index, delta) if delta else conv

    previous = _open_message_index(conv)
    if previous is not None:
        closed = dataclasses.replace(conv.messages[previous], streaming=False)
        conv = _replace_message(conv, previous, closed)
    msg = ChatMessage(id=event.message_id, role=_role(event.role), content=delta, streaming=True)
    return _append_message(conv, msg)


# --- tool calls ----------------------------------------------------------------------------


def _reject_constant(name: str) -> object:
    """``NaN``/``Infinity`` are not JSON: re-sending them upstream would be invalid."""
    raise ValueError(f"non-standard JSON constant {name}")


def _parse_args(text: str) -> JsonObject | None:
    """Parse accumulated args; an empty text is ``{}``. Non-objects are invalid."""
    if not text.strip():
        return {}
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        # RecursionError: pathologically nested input must not break totality (REQ-005).
        return None
    return value if isinstance(value, dict) else None


def _end_call(call: ToolCall) -> ToolCall:
    """REQ-009.3, REQ-009.7: the args are complete; parse them and hand the call over."""
    args = _parse_args(call.args_text)
    if args is None:
        return dataclasses.replace(call, status=ToolCallStatus.ERROR, result=INVALID_TOOL_ARGUMENTS)
    return dataclasses.replace(call, args=args, status=ToolCallStatus.RUNNING)


def _replace_call(conv: ConversationState, call: ToolCall, **changes: Any) -> ConversationState:
    index = conv._tool_index[call.id]
    calls = (*conv.tool_calls[:index], call, *conv.tool_calls[index + 1 :])
    return conv.with_(tool_calls=calls, **changes)


def _unknown_call(
    conv: ConversationState, call_id: str | None, event_type: str
) -> ConversationState:
    return _diag(
        conv,
        "warning",
        DiagnosticCode.UNKNOWN_TOOL_CALL_ID,
        f"ignored {event_type} for unknown tool call {call_id!r}",
        event_type,
    )


def _link_parent(
    conv: ConversationState, call_id: str, parent_id: str | None
) -> tuple[ConversationState, str]:
    """Attach the call to its assistant message, creating the message if needed.

    Egress (DM §7.3) re-sends a call inside its assistant message, so every call needs
    one. Without ``parentMessageId`` the call joins the last message when it is the
    assistant's; otherwise a message with the deterministic ID ``assistant-<call_id>``
    is created (the reducer must not generate random IDs).
    """
    if parent_id is None:
        last = conv.messages[-1] if conv.messages else None
        parent_id = (
            last.id if last is not None and last.role is MessageRole.ASSISTANT else None
        ) or f"assistant-{call_id}"
    index = conv._message_index.get(parent_id)
    if index is None:
        parent = ChatMessage(id=parent_id, role=MessageRole.ASSISTANT, tool_call_ids=(call_id,))
        return _append_message(conv, parent), parent_id
    msg = conv.messages[index]
    linked = dataclasses.replace(msg, tool_call_ids=(*msg.tool_call_ids, call_id))
    return _replace_message(conv, index, linked), parent_id


def _start_call(
    conv: ConversationState, call_id: str, name: str, parent_id: str | None, event_type: str
) -> ConversationState:
    if call_id in conv._tool_index:
        return _diag(
            conv,
            "warning",
            DiagnosticCode.DUPLICATE_ID,
            f"ignored a second start of tool call {call_id!r}",
            event_type,
        )
    conv, parent_id = _link_parent(conv, call_id, parent_id)
    call = ToolCall(
        id=call_id,
        name=name,
        parent_message_id=parent_id,
        is_client_tool=name in conv.config.client_tool_names,
    )
    return conv.with_(tool_calls=(*conv.tool_calls, call))


def _too_large(text: str, limit: int) -> bool:
    # A UTF-8 character is at most 4 bytes: skip encoding while clearly under the cap.
    return len(text) * 4 > limit and len(text.encode("utf-8")) > limit


def _append_args(
    conv: ConversationState, call: ToolCall, delta: str, event_type: str
) -> ConversationState:
    if call.status is not ToolCallStatus.STREAMING or not delta:
        return conv
    text = call.args_text + delta
    limit = conv.config.max_args_bytes
    if _too_large(text, limit):
        failed = dataclasses.replace(
            call,
            args_text="",
            status=ToolCallStatus.ERROR,
            result=f"Invalid tool arguments: the arguments exceed {limit} bytes.",
        )
        conv = _replace_call(conv, failed, dirty_tool_args=conv.dirty_tool_args - {call.id})
        return _diag(
            conv,
            "warning",
            DiagnosticCode.ARGS_TOO_LARGE,
            f"tool call {call.id!r} arguments exceed {limit} bytes",
            event_type,
        )
    return _replace_call(
        conv,
        dataclasses.replace(call, args_text=text),
        dirty_tool_args=conv.dirty_tool_args | {call.id},
    )


def _finish_call(conv: ConversationState, call: ToolCall) -> ConversationState:
    if call.status is not ToolCallStatus.STREAMING:
        return conv
    return _replace_call(conv, _end_call(call), dirty_tool_args=conv.dirty_tool_args - {call.id})


def _get_call(conv: ConversationState, call_id: str) -> ToolCall | None:
    index = conv._tool_index.get(call_id)
    return None if index is None else conv.tool_calls[index]


def _tool_start(conv: ConversationState, event: ToolCallStartEvent) -> ConversationState:
    """REQ-009.1, REQ-018.2: add a streaming call, link its parent, mark client tools."""
    return _start_call(
        conv,
        event.tool_call_id,
        event.tool_call_name,
        event.parent_message_id,
        EventType.TOOL_CALL_START.value,
    )


def _tool_args(conv: ConversationState, event: ToolCallArgsEvent) -> ConversationState:
    """REQ-009.2: accumulate args; parsing is deferred (``dirty_tool_args``, DM H-3)."""
    event_type = EventType.TOOL_CALL_ARGS.value
    call = _get_call(conv, event.tool_call_id)
    if call is None:
        return _unknown_call(conv, event.tool_call_id, event_type)
    return _append_args(conv, call, event.delta, event_type)


def _tool_end(conv: ConversationState, event: ToolCallEndEvent) -> ConversationState:
    """REQ-009.3, REQ-009.7: parse the args; ``running`` or ``error``."""
    call = _get_call(conv, event.tool_call_id)
    if call is None:
        return _unknown_call(conv, event.tool_call_id, EventType.TOOL_CALL_END.value)
    return _finish_call(conv, call)


def _open_call(conv: ConversationState) -> ToolCall | None:
    """The call an ID-less chunk continues: the last one still streaming."""
    for call in reversed(conv.tool_calls):
        if call.status is ToolCallStatus.STREAMING:
            return call
    return None


def _tool_chunk(conv: ConversationState, event: ToolCallChunkEvent) -> ConversationState:
    """REQ-009.5: chunks are START (new ID) + ARGS; a new chunk call ENDs the previous one."""
    event_type = EventType.TOOL_CALL_CHUNK.value
    delta = event.delta or ""
    call_id = event.tool_call_id
    call = _get_call(conv, call_id) if call_id is not None else _open_call(conv)
    if call is not None:
        return _append_args(conv, call, delta, event_type)
    if call_id is None or not event.tool_call_name:
        return _unknown_call(conv, call_id, event_type)
    previous = _open_call(conv)
    if previous is not None:
        conv = _finish_call(conv, previous)
    conv = _start_call(conv, call_id, event.tool_call_name, event.parent_message_id, event_type)
    return _append_args(conv, conv.tool_calls[-1], delta, event_type)


def _content_text(content: str | list[Any]) -> str:
    """Flatten AG-UI 1.0 multimodal tool-result content to text (DM §7.1 v1.3).

    Text parts are concatenated; other parts become ``[<type>]`` placeholders, because
    v0.1 renders and re-sends tool results as text only.
    """
    if isinstance(content, str):
        return content
    pieces: list[str] = []
    for part in content:
        text = getattr(part, "text", None)
        pieces.append(text if isinstance(text, str) else f"[{getattr(part, 'type', 'content')}]")
    return "".join(pieces)


def _tool_result(conv: ConversationState, event: ToolCallResultEvent) -> ConversationState:
    """REQ-009.4: store the result, ``done``, and append the ``tool`` message once."""
    call = _get_call(conv, event.tool_call_id)
    if call is None:
        return _unknown_call(conv, event.tool_call_id, EventType.TOOL_CALL_RESULT.value)
    content = _content_text(event.content)
    conv = _finish_call(conv, call)
    call = conv.tool_calls[conv._tool_index[call.id]]
    # ``rejected`` and ``error`` are terminal (API §4.6, DM v1.9): the result is recorded,
    # the status stays. PydanticAI answers a rejected approval with the denial text.
    terminal = call.status in (ToolCallStatus.REJECTED, ToolCallStatus.ERROR)
    status = call.status if terminal else ToolCallStatus.DONE
    conv = _replace_call(conv, dataclasses.replace(call, status=status, result=content))
    if event.message_id in conv._message_index:
        return conv
    tool_message = ChatMessage(
        id=event.message_id,
        role=MessageRole.TOOL,
        content=content,
        tool_call_id=call.id,
    )
    return _append_message(conv, tool_message)


# --- shared state --------------------------------------------------------------------------


def _state_snapshot(conv: ConversationState, event: StateSnapshotEvent) -> ConversationState:
    """REQ-016.1, REQ-016.4: replace ``shared_state`` and clear ``shared_state_stale``."""
    snapshot: object = event.snapshot
    if isinstance(snapshot, dict):
        try:
            copied: JsonObject = copy.deepcopy(snapshot)
        except RecursionError:
            snapshot = None  # pathologically deep: treated as invalid below (REQ-005.1)
        else:
            return conv.with_(shared_state=copied, shared_state_stale=False)
    conv = conv.with_(shared_state_stale=True, error_code=ErrorCode.SHARED_STATE_INVALID)
    return _diag(
        conv,
        "warning",
        DiagnosticCode.INVALID_EVENT,
        "ignored a STATE_SNAPSHOT that is not a JSON object; shared state is stale",
        EventType.STATE_SNAPSHOT.value,
    )


def _state_delta(conv: ConversationState, event: StateDeltaEvent) -> ConversationState:
    """REQ-016.2-3: apply RFC 6902 ops atomically; on failure keep the state, mark stale."""
    try:
        ops: list[JsonObject] = [
            op.model_dump(mode="json", by_alias=True, exclude_unset=True) for op in event.delta
        ]
        state = apply_patch(conv.shared_state, ops)
    except PatchError as exc:
        conv = conv.with_(shared_state_stale=True, error_code=ErrorCode.SHARED_STATE_PATCH_FAILED)
        return _diag(
            conv, "warning", DiagnosticCode.PATCH_FAILED, str(exc), EventType.STATE_DELTA.value
        )
    return conv.with_(shared_state=state)


# --- CUSTOM --------------------------------------------------------------------------------


def _custom(conv: ConversationState, event: CustomEvent) -> ConversationState:
    """REQ-010.5, INV-9: keep the latest ``custom_events_limit`` events."""
    limit = conv.config.custom_events_limit
    if limit <= 0:
        return conv
    record = CustomEventRecord(name=event.name, value=event.value, run_id=conv.run_id)
    return conv.with_(custom_events=(*conv.custom_events, record)[-limit:])


# --- reasoning -----------------------------------------------------------------------------


def _reasoning_position(conv: ConversationState, record_id: str) -> int | None:
    for index, record in enumerate(conv.reasoning):
        if record.id == record_id:
            return index
    return None


def _replace_reasoning(
    conv: ConversationState, index: int, record: ReasoningRecord
) -> ConversationState:
    return conv.with_(reasoning=(*conv.reasoning[:index], record, *conv.reasoning[index + 1 :]))


def _add_reasoning(conv: ConversationState, record_id: str, content: str) -> ConversationState:
    return conv.with_(reasoning=(*conv.reasoning, ReasoningRecord(id=record_id, content=content)))


def _reasoning_delta(conv: ConversationState, index: int, delta: str) -> ConversationState:
    record = conv.reasoning[index]
    return _replace_reasoning(
        conv, index, dataclasses.replace(record, content=record.content + delta)
    )


def _reasoning_unknown(
    conv: ConversationState, record_id: str | None, event_type: str
) -> ConversationState:
    return _diag(
        conv,
        "warning",
        DiagnosticCode.UNKNOWN_MESSAGE_ID,
        f"ignored {event_type} for unknown reasoning message {record_id!r}",
        event_type,
    )


def _reasoning_boundary(conv: ConversationState, event: BaseEvent) -> ConversationState:
    """``REASONING_START``/``REASONING_END`` only frame the phase; nothing to record."""
    return conv


def _reasoning_start(
    conv: ConversationState, event: ReasoningMessageStartEvent
) -> ConversationState:
    """REQ-011.1: start a reasoning record; it links to the turn's next assistant message."""
    if _reasoning_position(conv, event.message_id) is not None:
        return _diag(
            conv,
            "warning",
            DiagnosticCode.DUPLICATE_ID,
            f"ignored a second start of reasoning message {event.message_id!r}",
            EventType.REASONING_MESSAGE_START.value,
        )
    return _add_reasoning(conv, event.message_id, "")


def _reasoning_content(
    conv: ConversationState, event: ReasoningMessageContentEvent
) -> ConversationState:
    """REQ-011.1: accumulate reasoning text (creating the record if it is unknown)."""
    index = _reasoning_position(conv, event.message_id)
    if index is not None:
        return _reasoning_delta(conv, index, event.delta)
    return _diag(
        _add_reasoning(conv, event.message_id, event.delta),
        "warning",
        DiagnosticCode.IMPLICIT_MESSAGE,
        f"created reasoning message {event.message_id!r} implicitly",
        EventType.REASONING_MESSAGE_CONTENT.value,
    )


def _reasoning_end(conv: ConversationState, event: ReasoningMessageEndEvent) -> ConversationState:
    """REQ-011.1: records have no streaming flag; END only checks the ID."""
    if _reasoning_position(conv, event.message_id) is None:
        return _reasoning_unknown(conv, event.message_id, EventType.REASONING_MESSAGE_END.value)
    return conv


def _reasoning_chunk(
    conv: ConversationState, event: ReasoningMessageChunkEvent
) -> ConversationState:
    """REQ-011.1: a new ID starts a record; an ID-less chunk continues the last one."""
    delta = event.delta or ""
    if event.message_id is None:
        if not conv.reasoning:
            return _reasoning_unknown(conv, None, EventType.REASONING_MESSAGE_CHUNK.value)
        return _reasoning_delta(conv, len(conv.reasoning) - 1, delta) if delta else conv
    index = _reasoning_position(conv, event.message_id)
    if index is None:
        return _add_reasoning(conv, event.message_id, delta)
    return _reasoning_delta(conv, index, delta) if delta else conv


def _reasoning_encrypted(
    conv: ConversationState, event: ReasoningEncryptedValueEvent
) -> ConversationState:
    """REQ-011.2: keep the opaque value server-side on its reasoning record (Art. 3).

    Values for tool calls or for non-reasoning messages are not retained in v0.1
    (DM §7.1 v1.4).
    """
    index = _reasoning_position(conv, event.entity_id) if event.subtype == "message" else None
    if index is None:
        return _diag(
            conv,
            "debug",
            DiagnosticCode.IGNORED_EVENT,
            f"encrypted value for {event.subtype} {event.entity_id!r} is not retained in v0.1",
            EventType.REASONING_ENCRYPTED_VALUE.value,
        )
    record = dataclasses.replace(conv.reasoning[index], encrypted_value=event.encrypted_value)
    return _replace_reasoning(conv, index, record)


# --- MESSAGES_SNAPSHOT ---------------------------------------------------------------------


def _snapshot_call(
    conv: ConversationState, tool_call: Any, parent_id: str, results: dict[str, Any]
) -> ToolCall:
    """A record for a call listed in the snapshot: the existing one, or a new one."""
    existing = _get_call(conv, tool_call.id)
    if existing is not None:
        return existing
    name = tool_call.function.name
    call = _end_call(
        ToolCall(
            id=tool_call.id,
            name=name,
            args_text=tool_call.function.arguments,
            parent_message_id=parent_id,
            is_client_tool=name in conv.config.client_tool_names,
        )
    )
    result = results.get(tool_call.id)
    if result is not None:
        status = ToolCallStatus.ERROR if result.error else ToolCallStatus.DONE
        call = dataclasses.replace(call, status=status, result=_content_text(result.content))
    return call


def _messages_snapshot(conv: ConversationState, event: MessagesSnapshotEvent) -> ConversationState:
    """REQ-010.4, DM §7.1: rebuild ``messages`` from the snapshot.

    Tool calls still listed keep their records (and statuses); others are dropped; calls
    known only from the snapshot get new records. Reasoning messages become records
    linked to the next assistant message (else the previous one); streamed reasoning of
    surviving assistant messages is kept, so encrypted values are not lost. Activity
    messages are not rendered. Repeated IDs and tool messages for unknown calls are
    dropped with warnings (INV-1, INV-3).
    """
    event_type = EventType.MESSAGES_SNAPSHOT.value
    results = {m.tool_call_id: m for m in event.messages if m.role == "tool"}
    messages: list[ChatMessage] = []
    calls: list[ToolCall] = []
    snapshot_reasoning: list[ReasoningRecord] = []
    seen: set[str] = set()
    pending: list[int] = []
    last_assistant: str | None = None
    problems: list[tuple[DiagnosticCode, str]] = []

    for m in event.messages:
        if m.role == "activity":
            continue
        if m.id in seen:
            problems.append((DiagnosticCode.DUPLICATE_ID, f"dropped repeated message {m.id!r}"))
            continue
        seen.add(m.id)
        if m.role == "reasoning":
            pending.append(len(snapshot_reasoning))
            snapshot_reasoning.append(
                ReasoningRecord(id=m.id, content=m.content or "", encrypted_value=m.encrypted_value)
            )
            continue
        if m.role == "tool":
            if m.tool_call_id not in {c.id for c in calls}:
                problems.append(
                    (
                        DiagnosticCode.UNKNOWN_TOOL_CALL_ID,
                        f"dropped tool message {m.id!r} for unknown tool call {m.tool_call_id!r}",
                    )
                )
                continue
            messages.append(
                ChatMessage(
                    id=m.id,
                    role=MessageRole.TOOL,
                    content=_content_text(m.content),
                    tool_call_id=m.tool_call_id,
                    is_error=bool(m.error),
                )
            )
            continue
        if m.role == "assistant":
            call_ids: list[str] = []
            for tool_call in m.tool_calls or []:
                if tool_call.id in call_ids or any(c.id == tool_call.id for c in calls):
                    continue
                calls.append(_snapshot_call(conv, tool_call, m.id, results))
                call_ids.append(tool_call.id)
            messages.append(
                ChatMessage(
                    id=m.id,
                    role=MessageRole.ASSISTANT,
                    content=_content_text(m.content or ""),
                    tool_call_ids=tuple(call_ids),
                )
            )
            for index in pending:
                snapshot_reasoning[index] = dataclasses.replace(
                    snapshot_reasoning[index], assistant_message_id=m.id
                )
            pending.clear()
            last_assistant = m.id
            continue
        messages.append(
            ChatMessage(id=m.id, role=MessageRole(m.role), content=_content_text(m.content))
        )

    for index in pending:
        snapshot_reasoning[index] = dataclasses.replace(
            snapshot_reasoning[index], assistant_message_id=last_assistant
        )
    message_ids = {msg.id for msg in messages}
    snapshot_ids = {r.id for r in snapshot_reasoning}
    kept_reasoning = tuple(
        r
        for r in conv.reasoning
        if r.id not in snapshot_ids
        and (r.assistant_message_id is None or r.assistant_message_id in message_ids)
    )
    call_id_set = {c.id for c in calls}
    conv = conv.with_(
        messages=tuple(messages),
        tool_calls=tuple(calls),
        reasoning=(*kept_reasoning, *snapshot_reasoning),
        dirty_tool_args=conv.dirty_tool_args & call_id_set,
    )
    for code, message in problems:
        conv = _diag(conv, "warning", code, message, event_type)
    return conv


_HANDLERS: dict[str, Handler] = {
    EventType.RUN_STARTED: _run_started,
    EventType.RUN_FINISHED: _run_finished,
    EventType.RUN_ERROR: _run_error,
    EventType.STEP_STARTED: _step_started,
    EventType.STEP_FINISHED: _step_finished,
    EventType.TEXT_MESSAGE_START: _text_start,
    EventType.TEXT_MESSAGE_CONTENT: _text_content,
    EventType.TEXT_MESSAGE_END: _text_end,
    EventType.TEXT_MESSAGE_CHUNK: _text_chunk,
    EventType.TOOL_CALL_START: _tool_start,
    EventType.TOOL_CALL_ARGS: _tool_args,
    EventType.TOOL_CALL_END: _tool_end,
    EventType.TOOL_CALL_CHUNK: _tool_chunk,
    EventType.TOOL_CALL_RESULT: _tool_result,
    EventType.STATE_SNAPSHOT: _state_snapshot,
    EventType.STATE_DELTA: _state_delta,
    EventType.MESSAGES_SNAPSHOT: _messages_snapshot,
    EventType.CUSTOM: _custom,
    EventType.REASONING_START: _reasoning_boundary,
    EventType.REASONING_MESSAGE_START: _reasoning_start,
    EventType.REASONING_MESSAGE_CONTENT: _reasoning_content,
    EventType.REASONING_MESSAGE_END: _reasoning_end,
    EventType.REASONING_MESSAGE_CHUNK: _reasoning_chunk,
    EventType.REASONING_END: _reasoning_boundary,
    EventType.REASONING_ENCRYPTED_VALUE: _reasoning_encrypted,
}

HANDLED_EVENT_TYPES: frozenset[str] = frozenset(_HANDLERS) | _IGNORED
"""Event types the reducer applies or deliberately ignores (all others are unknown)."""


# --- public API ----------------------------------------------------------------------------


def reduce(state: ConversationState, event: BaseEvent) -> ConversationState:
    """Apply one validated AG-UI event to ``state`` and return the new state.

    Pure, deterministic and total (REQ-005.1-2): it never mutates ``state`` and never
    raises for a validated event; problems become diagnostics on the result.
    """
    event_type = _type_name(event.type)
    if event_type in _IGNORED:
        return _diag(
            state,
            "debug",
            DiagnosticCode.IGNORED_EVENT,
            f"{event_type} is accepted but not rendered",
            event_type,
        )
    handler = _HANDLERS.get(event_type)
    if handler is not None and state.run_status is not RunStatus.RUNNING:
        # Only a running run accepts events: nothing can reopen a stream after the end
        # (INV-5). RUN_FINISHED of another run still reports itself as stale first.
        if isinstance(event, RunFinishedEvent) and event.run_id not in state.last_run_ids:
            return _stale(state, event.run_id, event_type)
        return _after_end(state, event_type)
    if handler is None:
        return _diag(
            state,
            "debug",
            DiagnosticCode.UNKNOWN_EVENT_TYPE,
            f"skipped {event_type}: no handler for this event type",
            event_type,
        )
    return handler(state, event)


def parse_event(raw: object) -> BaseEvent | Diagnostic:
    """Validate one wire event (camelCase JSON object) into its ``ag_ui.core`` model.

    Returns a :class:`Diagnostic` instead of raising: ``UNKNOWN_EVENT_TYPE`` (debug) for
    unknown or deprecated types such as ``THINKING_*`` (REQ-012.2), and ``INVALID_EVENT``
    (warning, naming the type) for anything that fails validation (REQ-012.3).
    """
    if not isinstance(raw, Mapping):
        return Diagnostic(
            level="warning",
            code=DiagnosticCode.INVALID_EVENT,
            message=f"skipped an event that is not a JSON object ({type(raw).__name__})",
        )
    event_type = raw.get("type")
    if not isinstance(event_type, str):
        return Diagnostic(
            level="warning",
            code=DiagnosticCode.INVALID_EVENT,
            message="skipped an event without a string 'type'",
        )
    if event_type not in _KNOWN_TYPES:
        return Diagnostic(
            level="debug",
            code=DiagnosticCode.UNKNOWN_EVENT_TYPE,
            message=f"skipped {event_type}: unknown to the installed ag-ui-protocol",
            event_type=event_type,
        )
    try:
        event: BaseEvent = _EVENT_ADAPTER.validate_python(raw)
    except ValidationError as exc:
        locations = ", ".join(
            ".".join(str(part) for part in error["loc"]) or "<event>" for error in exc.errors()
        )
        return Diagnostic(
            level="warning",
            code=DiagnosticCode.INVALID_EVENT,
            message=f"skipped an invalid {event_type} event (invalid fields: {locations})",
            event_type=event_type,
        )
    return event
