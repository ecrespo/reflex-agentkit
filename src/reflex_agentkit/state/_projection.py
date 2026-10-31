"""The projection of a conversation onto the public state vars (DM §7.2, DD-008).

Pure functions, no Reflex: ``AgentState`` writes the :class:`Projection` onto its public
vars at every flush. Backend-only data (encrypted reasoning values, interrupt answers,
remembered interrupt IDs, the config) is never part of it (INV-11, REQ-025).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    CustomEventRecord,
    MessageRole,
    OpenInterrupt,
    PendingInterrupt,
    RunStatus,
    ToolCall,
)

__all__ = ["VISIBLE_ROLES", "Projection", "project", "refresh_dirty_args"]

VISIBLE_ROLES = frozenset({MessageRole.USER, MessageRole.ASSISTANT, MessageRole.TOOL})
"""The message roles shown in the browser; system and developer messages are not."""


@dataclasses.dataclass(frozen=True, slots=True)
class Projection:
    """The values of the public vars of API §4.2."""

    messages: list[ChatMessage]
    tool_calls: list[ToolCall]
    pending_interrupt: PendingInterrupt | None
    shared_state: dict[str, Any]
    shared_state_stale: bool
    run_status: RunStatus
    current_step: str
    thread_id: str
    run_id: str
    error: str
    error_code: ErrorCode | None
    custom_events: list[CustomEventRecord]


def refresh_dirty_args(conv: ConversationState) -> ConversationState:
    """Parse the streaming args of the calls in ``dirty_tool_args`` (DM H-3).

    A call whose accumulated text is a valid JSON object gets it as ``args``; the others
    keep theirs. The set is cleared. Without dirty calls ``conv`` is returned unchanged.
    """
    if not conv.dirty_tool_args:
        return conv
    calls = list(conv.tool_calls)
    for call_id in conv.dirty_tool_args:
        index = conv._tool_index.get(call_id)
        if index is None:
            continue
        parsed = _parse_object(calls[index].args_text)
        if parsed is not None:
            calls[index] = dataclasses.replace(calls[index], args=parsed)
    return conv.with_(tool_calls=tuple(calls), dirty_tool_args=frozenset())


def _parse_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def project(conv: ConversationState) -> Projection:
    """Compute the public vars from ``conv`` (DM §7.2)."""
    conv = refresh_dirty_args(conv)
    reasoning = {
        r.assistant_message_id: r.content for r in conv.reasoning if r.assistant_message_id
    }
    messages = [
        dataclasses.replace(m, reasoning=reasoning[m.id]) if m.id in reasoning else m
        for m in conv.messages
        if m.role in VISIBLE_ROLES
    ]
    return Projection(
        messages=messages,
        tool_calls=list(conv.tool_calls),
        pending_interrupt=_pending_interrupt(conv),
        shared_state=json.loads(json.dumps(conv.shared_state)),
        shared_state_stale=conv.shared_state_stale,
        run_status=conv.run_status,
        current_step=conv.current_step,
        thread_id=conv.thread_id,
        run_id=conv.run_id,
        error=conv.error,
        error_code=conv.error_code,
        custom_events=list(conv.custom_events),
    )


def _pending_interrupt(conv: ConversationState) -> PendingInterrupt | None:
    """The first unanswered generic interrupt, with its place in the queue (REQ-014.3)."""
    generic: list[OpenInterrupt] = [
        i for i in conv.interrupts if i.tool_call_id is None and not i.is_local
    ]
    for position, interrupt in enumerate(generic, start=1):
        if interrupt.id not in conv.answers:
            return PendingInterrupt(
                id=interrupt.id,
                reason=interrupt.reason,
                message=interrupt.message,
                payload=interrupt.payload,
                response_schema=interrupt.response_schema,
                queue_position=position,
                queue_size=len(generic),
            )
    return None
