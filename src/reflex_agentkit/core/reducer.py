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
)
from pydantic import TypeAdapter, ValidationError

from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    Diagnostic,
    DiagnosticCode,
    DiagnosticLevel,
    RunStatus,
    ToolCallStatus,
)

__all__ = ["HANDLED_EVENT_TYPES", "parse_event", "reduce"]

Handler = Callable[[ConversationState, Any], ConversationState]

_EVENT_ADAPTER: TypeAdapter[Any] = TypeAdapter(Event)
_KNOWN_TYPES = frozenset(member.value for member in EventType)

INCOMPLETE_TOOL_CALL = "The run ended before the tool call's arguments were complete."

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


def _close_streams(conv: ConversationState) -> ConversationState:
    """End every open stream when the run ends (REQ-008.6, INV-5)."""
    changes: dict[str, Any] = {}
    if any(m.streaming for m in conv.messages):
        changes["messages"] = tuple(
            dataclasses.replace(m, streaming=False) if m.streaming else m for m in conv.messages
        )
    if any(c.status is ToolCallStatus.STREAMING for c in conv.tool_calls):
        changes["tool_calls"] = tuple(
            dataclasses.replace(c, status=ToolCallStatus.ERROR, result=INCOMPLETE_TOOL_CALL)
            if c.status is ToolCallStatus.STREAMING
            else c
            for c in conv.tool_calls
        )
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
        f"ignored {event_type}: the run already ended with status {conv.run_status.value!r}",
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
    if conv.run_status is not RunStatus.RUNNING:
        return _after_end(conv, EventType.RUN_FINISHED.value)
    return _close_streams(conv).with_(run_status=RunStatus.IDLE)


def _run_error(conv: ConversationState, event: RunErrorEvent) -> ConversationState:
    """REQ-004.3: the run failed; the content streamed so far is kept."""
    if conv.run_status is not RunStatus.RUNNING:
        return _after_end(conv, EventType.RUN_ERROR.value)
    return _close_streams(conv).with_(
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


_HANDLERS: dict[str, Handler] = {
    EventType.RUN_STARTED: _run_started,
    EventType.RUN_FINISHED: _run_finished,
    EventType.RUN_ERROR: _run_error,
    EventType.STEP_STARTED: _step_started,
    EventType.STEP_FINISHED: _step_finished,
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
