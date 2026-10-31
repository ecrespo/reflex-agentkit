"""Pure command functions: state transitions that are not AG-UI events (API §11).

Each takes a ``ConversationState`` and returns a new one (or the same object when the
command does not apply). They generate IDs (UUID4 by default, DM R-7) but take ``new_id``
so a sequence of commands can be reproduced.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterable
from dataclasses import replace

from ag_ui.core import ResumeEntry

from reflex_agentkit.core._patch import PatchError, apply_patch
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
    "LOCAL_INTERRUPT_PREFIX",
    "MAX_PATCH_OPS",
    "MAX_PAYLOAD_BYTES",
    "all_answered",
    "apply_approval",
    "apply_cancel",
    "apply_client_tool_result",
    "apply_failure",
    "apply_interrupt_response",
    "apply_rejection",
    "apply_shared_state_patch",
    "apply_shared_state_write",
    "begin_retry",
    "begin_run",
    "new_thread",
    "request_local_approvals",
    "resume_entries",
    "revert_shared_state",
    "start_client_tool_round",
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


LOCAL_INTERRUPT_PREFIX = "local-"
"""Prefix of the interrupt IDs of client-tool approvals (DM §3.2, §3.4)."""


def request_local_approvals(conv: ConversationState, call_ids: Iterable[str]) -> ConversationState:
    """Pause on local approvals for approval-required client tools (REQ-018.3, Flow B.2).

    Each named call that is a running client-tool call moves to ``pending_approval``
    behind an ``OpenInterrupt`` with ``is_local=True`` and the ID ``local-<call_id>``.
    Local interrupts are answered by ``approve_tool``/``reject_tool`` and never sent
    upstream. Outside a running run, or with no such call, this is a no-op.
    """
    if conv.run_status is not RunStatus.RUNNING:
        return conv
    calls = list(conv.tool_calls)
    opened: list[OpenInterrupt] = []
    for call_id in dict.fromkeys(call_ids):
        index = conv._tool_index.get(call_id)
        if index is None:
            continue
        call = calls[index]
        if not call.is_client_tool or call.status is not ToolCallStatus.RUNNING:
            continue
        interrupt_id = f"{LOCAL_INTERRUPT_PREFIX}{call_id}"
        calls[index] = replace(
            call, status=ToolCallStatus.PENDING_APPROVAL, interrupt_id=interrupt_id
        )
        opened.append(
            OpenInterrupt(id=interrupt_id, reason="tool_call", tool_call_id=call_id, is_local=True)
        )
    if not opened:
        return conv
    return conv.with_(
        tool_calls=tuple(calls),
        interrupts=tuple(opened),
        answers={},
        run_status=RunStatus.AWAITING_INPUT,
    )


def start_client_tool_round(conv: ConversationState, *, max_rounds: int) -> ConversationState:
    """Count one client-tool round of the turn, or stop a looping model (DD-009).

    The round past ``max_rounds`` ends the run in ``error`` with
    ``CLIENT_TOOL_LOOP_LIMIT``. Outside a running run this is a no-op.
    """
    if conv.run_status is not RunStatus.RUNNING:
        return conv
    if conv.client_tool_rounds >= max_rounds:
        message = f"the agent called client tools in more than {max_rounds} consecutive rounds"
        return apply_failure(conv, ErrorCode.CLIENT_TOOL_LOOP_LIMIT, message)
    return conv.with_(client_tool_rounds=conv.client_tool_rounds + 1)


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


MAX_PATCH_OPS = 256
"""The most operations one app-side ``patch_shared_state`` call may carry."""


def _json_object_copy(value: object) -> JsonObject | None:
    """A deep copy of ``value`` if it is a finite JSON object within the payload cap."""
    if not isinstance(value, dict):
        return None
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return None
    if len(text.encode()) > MAX_PAYLOAD_BYTES:
        return None
    copied: JsonObject = json.loads(text)
    return copied


def _shared_state_error(
    conv: ConversationState, code: ErrorCode, message: str
) -> ConversationState:
    return conv.with_(error=message, error_code=code)


def apply_shared_state_write(conv: ConversationState, value: object) -> ConversationState:
    """Replace ``shared_state`` from app code (REQ-017.1-2, INV-10).

    Rejected while running (``SHARED_STATE_LOCKED``: the agent owns the state) and when
    the value is not a JSON object within :data:`MAX_PAYLOAD_BYTES`
    (``SHARED_STATE_INVALID``). The stored value is a copy; ``shared_state_stale`` clears.
    """
    if conv.run_status is RunStatus.RUNNING:
        return _shared_state_error(
            conv, ErrorCode.SHARED_STATE_LOCKED, "The shared state cannot change during a run."
        )
    copied = _json_object_copy(value)
    if copied is None:
        return _shared_state_error(
            conv,
            ErrorCode.SHARED_STATE_INVALID,
            f"The shared state must be a JSON object of at most {MAX_PAYLOAD_BYTES} bytes.",
        )
    return conv.with_(shared_state=copied, shared_state_stale=False)


def apply_shared_state_patch(conv: ConversationState, ops: object) -> ConversationState:
    """Apply RFC 6902 ``ops`` to ``shared_state`` atomically (REQ-017.1-2).

    Rejected while running (``SHARED_STATE_LOCKED``). A malformed, oversized or failing
    patch changes nothing and sets ``SHARED_STATE_PATCH_FAILED``.
    """
    if conv.run_status is RunStatus.RUNNING:
        return _shared_state_error(
            conv, ErrorCode.SHARED_STATE_LOCKED, "The shared state cannot change during a run."
        )
    failed = _shared_state_error(
        conv, ErrorCode.SHARED_STATE_PATCH_FAILED, "The shared-state patch could not be applied."
    )
    wrapped = _json_object_copy({"ops": ops})
    if wrapped is None or not isinstance(wrapped["ops"], list):
        return failed
    operations = wrapped["ops"]
    if len(operations) > MAX_PATCH_OPS or not all(isinstance(op, dict) for op in operations):
        return failed
    # One op at a time, with the size cap after each: ``copy``/``move`` ops can double the
    # document, so checking only the final result would allow exponential growth first.
    result = conv.shared_state
    for op in operations:
        try:
            result = apply_patch(result, [op])  # type: ignore[list-item]
        except PatchError:
            return failed
        if _json_object_copy(result) is None:
            return failed
    return conv.with_(shared_state=result, shared_state_stale=False)


def revert_shared_state(conv: ConversationState, previous: JsonObject) -> ConversationState:
    """Reject an agent update that fails ``shared_state_model`` (REQ-016.5).

    It behaves like a failed delta (REQ-016.3): ``previous`` is kept, the state is marked
    stale, ``error_code`` is ``SHARED_STATE_INVALID`` and a warning is recorded.
    """
    diagnostic = Diagnostic(
        level="warning",
        code=DiagnosticCode.INVALID_EVENT,
        message="The shared state did not validate against shared_state_model.",
    )
    return conv.with_(
        shared_state=previous,
        shared_state_stale=True,
        error_code=ErrorCode.SHARED_STATE_INVALID,
        diagnostics=(*conv.diagnostics, diagnostic),
    )


def begin_retry(
    conv: ConversationState,
    *,
    config: ReducerConfig,
    new_id: Callable[[], str] = _uuid4,
) -> ConversationState:
    """Start the last user turn again (REQ-028.1, API §4.3).

    Allowed only after ``error`` or ``cancelled``. Everything after the last ``user``
    message is dropped (with its tool calls and reasoning), and a new turn starts with a
    new ``run_id``; the round counter resets. Without a user message this is a no-op.
    """
    if conv.run_status not in (RunStatus.ERROR, RunStatus.CANCELLED):
        return conv
    last_user = next(
        (
            i
            for i in range(len(conv.messages) - 1, -1, -1)
            if conv.messages[i].role is MessageRole.USER
        ),
        None,
    )
    if last_user is None:
        return conv
    messages = conv.messages[: last_user + 1]
    kept = {m.id for m in messages}
    referenced = {call_id for m in messages for call_id in m.tool_call_ids}
    calls = tuple(c for c in conv.tool_calls if c.id in referenced or c.parent_message_id in kept)
    reasoning = tuple(r for r in conv.reasoning if r.assistant_message_id in kept)
    truncated = conv.with_(
        messages=messages,
        tool_calls=calls,
        reasoning=reasoning,
        dirty_tool_args=frozenset(),
        current_step="",
    )
    started = begin_run(truncated, config=config, new_id=new_id)
    return started.with_(last_run_ids=(started.run_id,), client_tool_rounds=0)


def new_thread(conv: ConversationState, *, new_id: Callable[[], str] = _uuid4) -> ConversationState:
    """Start a new conversation (REQ-002.3-4): cancel a live run, then reset everything."""
    if conv.run_status is RunStatus.RUNNING:
        conv = apply_cancel(conv)
    return ConversationState.initial(conv.config).with_(thread_id=new_id())
