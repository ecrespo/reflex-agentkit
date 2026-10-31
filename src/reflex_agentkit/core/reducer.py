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

import dataclasses
import json
from collections.abc import Callable, Mapping
from typing import Any

from ag_ui.core import (
    BaseEvent,
    Event,
    EventType,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
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

from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    Diagnostic,
    DiagnosticCode,
    DiagnosticLevel,
    JsonObject,
    MessageRole,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)

__all__ = ["HANDLED_EVENT_TYPES", "INVALID_TOOL_ARGUMENTS", "parse_event", "reduce"]

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


def _close_streams(conv: ConversationState, *, finished: bool) -> ConversationState:
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
    return conv.with_(**changes) if changes else conv


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


def _run_finished(conv: ConversationState, event: RunFinishedEvent) -> ConversationState:
    """REQ-004.1: the run completes; open streams are closed."""
    if event.run_id not in conv.last_run_ids:
        return _stale(conv, event.run_id, EventType.RUN_FINISHED.value)
    return _close_streams(conv, finished=True).with_(run_status=RunStatus.IDLE)


def _run_error(conv: ConversationState, event: RunErrorEvent) -> ConversationState:
    """REQ-004.3: the run failed; the content streamed so far is kept."""
    return _close_streams(conv, finished=False).with_(
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


def _parse_args(text: str) -> JsonObject | None:
    """Parse accumulated args; an empty text is ``{}``. Non-objects are invalid."""
    if not text.strip():
        return {}
    try:
        value = json.loads(text)
    except ValueError:
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
    conv = _replace_call(
        conv, dataclasses.replace(call, status=ToolCallStatus.DONE, result=content)
    )
    if event.message_id in conv._message_index:
        return conv
    tool_message = ChatMessage(
        id=event.message_id,
        role=MessageRole.TOOL,
        content=content,
        tool_call_id=call.id,
    )
    return _append_message(conv, tool_message)


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
