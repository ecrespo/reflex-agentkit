"""Pure command functions: state transitions that are not AG-UI events (API §11).

Each takes a ``ConversationState`` and returns a new one (or the same object when the
command does not apply). They generate IDs (UUID4 by default, DM R-7) but take ``new_id``
so a sequence of commands can be reproduced.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import replace

from ag_ui.core import ResumeEntry

from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    Diagnostic,
    DiagnosticCode,
    InterruptAnswer,
    JsonObject,
    JsonValue,
    MessageRole,
    OpenInterrupt,
    ReducerConfig,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from reflex_agentkit.core.reducer import close_streams

__all__ = [
    "CANCELLED_RESULT",
    "MAX_PAYLOAD_BYTES",
    "all_answered",
    "apply_approval",
    "apply_cancel",
    "apply_client_tool_result",
    "apply_failure",
    "apply_interrupt_response",
    "apply_rejection",
    "begin_run",
    "new_thread",
    "resume_entries",
]

MAX_PAYLOAD_BYTES = 64 * 1024
"""Cap on the serialized JSON of ``edited_args`` and interrupt responses (TD §6)."""

CANCELLED_RESULT = "cancelled"
"""Result text of the tool calls a cancellation interrupts (REQ-007.4, REQ-015.2)."""


def _uuid4() -> str:
    return str(uuid.uuid4())


def _too_large(value: JsonValue) -> bool:
    return len(json.dumps(value, ensure_ascii=False).encode()) > MAX_PAYLOAD_BYTES


def _parse_json(text: str) -> tuple[bool, JsonValue]:
    """``(True, value)`` if ``text`` is finite JSON within the nesting limit."""

    def reject(name: str) -> object:
        raise ValueError(name)

    try:
        return True, json.loads(text, parse_constant=reject)
    except (ValueError, RecursionError):
        return False, None


def all_answered(conv: ConversationState) -> bool:
    """Whether the pause has interrupts and every one of them has an answer (INV-4)."""
    return bool(conv.interrupts) and all(i.id in conv.answers for i in conv.interrupts)


def _record(
    conv: ConversationState, answer: InterruptAnswer, **changes: object
) -> ConversationState:
    """Store ``answer``; leave the pause once every interrupt is answered (DM v1.6)."""
    answers = {**conv.answers, answer.interrupt_id: answer}
    done = all(i.id in answers for i in conv.interrupts)
    status = RunStatus.IDLE if done else conv.run_status
    return conv.with_(answers=answers, run_status=status, **changes)


def _approvable(conv: ConversationState, call_id: str) -> tuple[ToolCall, OpenInterrupt] | None:
    """The pending call and its open, unanswered interrupt, if there is one (REQ-013.6)."""
    if conv.run_status is not RunStatus.AWAITING_INPUT:
        return None
    index = conv._tool_index.get(call_id)
    if index is None:
        return None
    call = conv.tool_calls[index]
    if call.status is not ToolCallStatus.PENDING_APPROVAL or call.interrupt_id in conv.answers:
        return None
    interrupt = next((i for i in conv.interrupts if i.id == call.interrupt_id), None)
    return None if interrupt is None else (call, interrupt)


def _with_call(conv: ConversationState, call: ToolCall) -> tuple[ToolCall, ...]:
    calls = list(conv.tool_calls)
    calls[conv._tool_index[call.id]] = call
    return tuple(calls)


def apply_approval(
    conv: ConversationState, call_id: str, edited_args: object = None
) -> ConversationState:
    """Approve a pending tool call, optionally with edited arguments (REQ-013.2-3, 013.7).

    A ``str`` ``edited_args`` is parsed as JSON. Edits that are not a JSON object or that
    exceed :data:`MAX_PAYLOAD_BYTES` serialized set ``INVALID_EDITED_ARGS`` and leave the
    call pending. Unknown or non-pending calls are ignored (REQ-013.6).
    """
    target = _approvable(conv, call_id)
    if target is None:
        return conv
    call, interrupt = target
    payload: JsonObject = {"approved": True}
    args = call.args
    if edited_args is not None:
        if isinstance(edited_args, str):
            ok, edited_args = _parse_json(edited_args)
            if not ok:
                return _invalid_edit(conv, "the edited arguments are not valid JSON")
        if not isinstance(edited_args, dict):
            return _invalid_edit(conv, "the edited arguments must be a JSON object")
        try:
            too_large = _too_large(edited_args)
        except (TypeError, ValueError, RecursionError):
            return _invalid_edit(conv, "the edited arguments are not serializable as JSON")
        if too_large:
            return _invalid_edit(conv, f"the edited arguments exceed {MAX_PAYLOAD_BYTES} bytes")
        args = edited_args
        payload["editedArgs"] = edited_args
    running = replace(call, status=ToolCallStatus.RUNNING, args=args)
    answer = InterruptAnswer(interrupt_id=interrupt.id, status="resolved", payload=payload)
    return _record(conv, answer, tool_calls=_with_call(conv, running))


def _invalid_edit(conv: ConversationState, reason: str) -> ConversationState:
    return conv.with_(
        error=f"Invalid edited arguments: {reason}.", error_code=ErrorCode.INVALID_EDITED_ARGS
    )


def apply_rejection(
    conv: ConversationState,
    call_id: str,
    reason: str | None = None,
    *,
    new_id: Callable[[], str] = _uuid4,
) -> ConversationState:
    """Reject a pending tool call (REQ-013.4, REQ-018.3).

    A local (client-tool) approval is answered locally: a rejection tool message is added
    so the follow-up run tells the agent.
    """
    target = _approvable(conv, call_id)
    if target is None:
        return conv
    call, interrupt = target
    payload: JsonObject = {"approved": False}
    if reason is not None:
        payload["reason"] = reason
    result = f"Rejected by the user: {reason}" if reason else "Rejected by the user."
    rejected = replace(call, status=ToolCallStatus.REJECTED, result=result)
    messages = conv.messages
    if interrupt.is_local:
        tool_msg = ChatMessage(
            id=new_id(), role=MessageRole.TOOL, content=result, tool_call_id=call.id, is_error=True
        )
        messages = (*messages, tool_msg)
    answer = InterruptAnswer(interrupt_id=interrupt.id, status="resolved", payload=payload)
    return _record(conv, answer, tool_calls=_with_call(conv, rejected), messages=messages)


def apply_interrupt_response(conv: ConversationState, payload: object) -> ConversationState:
    """Answer the first pending generic interrupt (REQ-014.2-4).

    A ``str`` payload is parsed as JSON when it is valid JSON and kept as a string
    otherwise. Payloads above :data:`MAX_PAYLOAD_BYTES` serialized are ignored with a
    warning diagnostic. With no generic interrupt pending, nothing changes.
    """
    if conv.run_status is not RunStatus.AWAITING_INPUT:
        return conv
    target = next(
        (
            i
            for i in conv.interrupts
            if i.tool_call_id is None and not i.is_local and i.id not in conv.answers
        ),
        None,
    )
    if target is None:
        return conv
    value: object = payload
    if isinstance(payload, str):
        ok, parsed = _parse_json(payload)
        if ok:
            value = parsed
    try:
        too_large = _too_large(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, RecursionError):
        return _ignored(conv, "the interrupt response is not serializable as JSON")
    if too_large:
        return _ignored(conv, f"the interrupt response exceeds {MAX_PAYLOAD_BYTES} bytes")
    answer = InterruptAnswer(interrupt_id=target.id, status="resolved", payload=value)  # type: ignore[arg-type]
    return _record(conv, answer)


def _ignored(conv: ConversationState, reason: str) -> ConversationState:
    diagnostic = Diagnostic(
        level="warning", code=DiagnosticCode.IGNORED_EVENT, message=f"Ignored: {reason}."
    )
    return conv.with_(diagnostics=(*conv.diagnostics, diagnostic))


def apply_cancel(conv: ConversationState) -> ConversationState:
    """Cancel the run (REQ-007.4, REQ-015.1-2).

    While running, partial content is kept, streaming stops, and streaming or running
    calls end in ``error`` with the result ``"cancelled"``. While paused, pending approvals
    become ``rejected``; the non-local interrupt IDs move to ``abandoned_interrupt_ids``
    so the next run cancels them (REQ-015.3), and the pause bookkeeping is cleared. In
    any other status this is a no-op.
    """
    if conv.run_status is RunStatus.RUNNING:
        messages = tuple(replace(m, streaming=False) if m.streaming else m for m in conv.messages)
        open_states = (ToolCallStatus.STREAMING, ToolCallStatus.RUNNING)
        calls = tuple(
            replace(c, status=ToolCallStatus.ERROR, result=CANCELLED_RESULT)
            if c.status in open_states
            else c
            for c in conv.tool_calls
        )
        return conv.with_(
            run_status=RunStatus.CANCELLED,
            messages=messages,
            tool_calls=calls,
            dirty_tool_args=frozenset(),
            current_step="",
        )
    if conv.run_status is RunStatus.AWAITING_INPUT:
        calls = tuple(
            replace(c, status=ToolCallStatus.REJECTED, result=CANCELLED_RESULT)
            if c.status is ToolCallStatus.PENDING_APPROVAL
            else c
            for c in conv.tool_calls
        )
        abandoned = tuple(i.id for i in conv.interrupts if not i.is_local)
        return conv.with_(
            run_status=RunStatus.CANCELLED,
            tool_calls=calls,
            interrupts=(),
            answers={},
            abandoned_interrupt_ids=(*conv.abandoned_interrupt_ids, *abandoned),
        )
    return conv


def apply_client_tool_result(
    conv: ConversationState,
    call_id: str,
    result: str,
    *,
    is_error: bool = False,
    new_id: Callable[[], str] = _uuid4,
) -> ConversationState:
    """Record a client-tool handler's result (REQ-018.2, REQ-018.4).

    Only a running client-tool call takes a result; it ends ``done`` (or ``error``) and a
    tool message is appended. A handler error is a tool result, never a run error.
    """
    index = conv._tool_index.get(call_id)
    if index is None:
        return conv
    call = conv.tool_calls[index]
    if not call.is_client_tool or call.status is not ToolCallStatus.RUNNING:
        return conv
    status = ToolCallStatus.ERROR if is_error else ToolCallStatus.DONE
    finished = replace(call, status=status, result=result)
    tool_msg = ChatMessage(
        id=new_id(), role=MessageRole.TOOL, content=result, tool_call_id=call_id, is_error=is_error
    )
    return conv.with_(tool_calls=_with_call(conv, finished), messages=(*conv.messages, tool_msg))


def apply_failure(conv: ConversationState, code: ErrorCode, message: str) -> ConversationState:
    """End a running run in ``error`` after a transport or agent failure (TD Flow E).

    The content streamed so far is kept: open messages stop streaming and calls whose
    arguments were still streaming fail as incomplete, exactly as for ``RUN_ERROR``
    (REQ-004.3-4). Outside a running run this is a no-op.
    """
    if conv.run_status is not RunStatus.RUNNING:
        return conv
    return close_streams(conv, finished=False).with_(
        run_status=RunStatus.ERROR, error=message, error_code=code
    )


def _resume_answers(conv: ConversationState) -> tuple[InterruptAnswer, ...]:
    """The resume entries of the next run (DM §3.10 v1.6, REQ-013.5, REQ-015.3)."""
    cancelled = tuple(
        InterruptAnswer(interrupt_id=i, status="cancelled") for i in conv.abandoned_interrupt_ids
    )
    resolved = tuple(
        conv.answers[i.id] for i in conv.interrupts if not i.is_local and i.id in conv.answers
    )
    return (*cancelled, *resolved)


def resume_entries(conv: ConversationState) -> list[ResumeEntry]:
    """The ``RunAgentInput.resume`` entries captured by the last ``begin_run``."""
    return [
        ResumeEntry(interrupt_id=a.interrupt_id, status=a.status)
        if a.status == "cancelled"
        else ResumeEntry(interrupt_id=a.interrupt_id, status=a.status, payload=a.payload)
        for a in conv.resume
    ]


def begin_run(
    conv: ConversationState,
    *,
    config: ReducerConfig,
    user_text: str | None = None,
    resume: bool = False,
    new_id: Callable[[], str] = _uuid4,
) -> ConversationState:
    """Start a run (REQ-001.1-3, REQ-002.1-2, REQ-010.2, REQ-013.5, REQ-015.3).

    With ``user_text`` the human's turn is appended, a new turn of run IDs starts and the
    client-tool round counter resets. Without it (a resume or a client-tool follow-up) the
    run joins the current turn, so late events of the turn's earlier runs are still
    recognized. Either way the answers and abandoned interrupts are captured in
    ``resume`` and the pause bookkeeping is cleared. While an interrupt is still
    unanswered (``awaiting_input``) no run can start, so the call is a no-op.

    Args:
        conv: The current conversation.
        config: The reducer settings for this run, built from the ``AgentState`` ClassVars.
        user_text: The validated text the user sent, if this run starts a new turn.
        resume: Whether this run answers interrupts. Informational: the entries come from
            the recorded answers either way.
        new_id: ID factory; UUID4 strings by default.
    """
    del resume
    if conv.run_status is RunStatus.AWAITING_INPUT:
        return conv  # REQ-015.1, DM v1.8: unanswered interrupts block a new run
    thread_id = conv.thread_id or new_id()
    run_id = new_id()
    messages = conv.messages
    rounds = conv.client_tool_rounds
    if user_text is not None:
        user_message = ChatMessage(id=new_id(), role=MessageRole.USER, content=user_text)
        messages = (*messages, user_message)
        last_run_ids: tuple[str, ...] = (run_id,)
        rounds = 0
    else:
        last_run_ids = (*conv.last_run_ids, run_id)
    return conv.with_(
        config=config,
        thread_id=thread_id,
        run_id=run_id,
        run_status=RunStatus.RUNNING,
        error="",
        error_code=None,
        messages=messages,
        last_run_ids=last_run_ids,
        resume=_resume_answers(conv),
        interrupts=(),
        answers={},
        abandoned_interrupt_ids=(),
        client_tool_rounds=rounds,
    )


def new_thread(conv: ConversationState, *, new_id: Callable[[], str] = _uuid4) -> ConversationState:
    """Start a new conversation (REQ-002.3-4): cancel a live run, then reset everything."""
    if conv.run_status is RunStatus.RUNNING:
        conv = apply_cancel(conv)
    return ConversationState.initial(conv.config).with_(thread_id=new_id())
