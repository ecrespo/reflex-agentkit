"""Checker for the ``ConversationState`` invariants INV-1…INV-11 (DM §4).

INV-12 (``reduce`` never mutates its input) is a property of the reducer and is
tested there. INV-11 is checked here on the conversation's public-candidate fields;
the projection layer adds its own secret-hygiene test once ``project()`` exists.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable

from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import MessageRole, RunStatus, ToolCallStatus

RUN_LEVEL_CODES = frozenset(
    {
        ErrorCode.AGENT_RUN_ERROR,
        ErrorCode.AGENT_HTTP_ERROR,
        ErrorCode.AGENT_STREAM_ERROR,
        ErrorCode.AGENT_EXCEPTION,
        ErrorCode.CLIENT_TOOL_LOOP_LIMIT,
    }
)


def _has_duplicates(ids: Iterable[str]) -> bool:
    return any(count > 1 for count in Counter(ids).values())


def find_violations(conv: ConversationState) -> list[str]:
    """Return the IDs (``"INV-n"``) of every invariant that ``conv`` violates."""
    violations: list[str] = []
    tool_ids = {c.id for c in conv.tool_calls}
    interrupt_ids = {i.id for i in conv.interrupts}
    unanswered = interrupt_ids - set(conv.answers)

    # INV-1: IDs are unique within each collection.
    if (
        _has_duplicates(m.id for m in conv.messages)
        or _has_duplicates(c.id for c in conv.tool_calls)
        or _has_duplicates(i.id for i in conv.interrupts)
        or _has_duplicates(r.id for r in conv.reasoning)
    ):
        violations.append("INV-1")

    # INV-2: the derived indexes match the tuples.
    if conv._tool_index != {c.id: i for i, c in enumerate(conv.tool_calls)} or (
        conv._message_index != {m.id: i for i, m in enumerate(conv.messages)}
    ):
        violations.append("INV-2")

    # INV-3: message references to tool calls resolve.
    for msg in conv.messages:
        if msg.role is MessageRole.TOOL and msg.tool_call_id not in tool_ids:
            violations.append("INV-3")
            break
        if msg.role is MessageRole.ASSISTANT and not set(msg.tool_call_ids) <= tool_ids:
            violations.append("INV-3")
            break

    # INV-4: awaiting_input <=> some open interrupt is unanswered.
    if (conv.run_status is RunStatus.AWAITING_INPUT) != bool(unanswered):
        violations.append("INV-4")

    # INV-5: nothing streams outside a running run.
    if conv.run_status is not RunStatus.RUNNING and (
        any(m.streaming for m in conv.messages)
        or any(c.status is ToolCallStatus.STREAMING for c in conv.tool_calls)
    ):
        violations.append("INV-5")

    # INV-6: a call pending approval names an unanswered open interrupt.
    for call in conv.tool_calls:
        if call.status is ToolCallStatus.PENDING_APPROVAL and call.interrupt_id not in unanswered:
            violations.append("INV-6")
            break

    # INV-7: answers only for open interrupts.
    if not set(conv.answers) <= interrupt_ids:
        violations.append("INV-7")

    # INV-8: run-level error codes imply the error status (one-directional).
    if conv.error_code in RUN_LEVEL_CODES and conv.run_status is not RunStatus.ERROR:
        violations.append("INV-8")

    # INV-9: the custom-event ring is bounded.
    if len(conv.custom_events) > conv.config.custom_events_limit:
        violations.append("INV-9")

    # INV-10: shared state is JSON and round-trips unchanged.
    try:
        if json.loads(json.dumps(conv.shared_state)) != conv.shared_state:
            violations.append("INV-10")
    except (TypeError, ValueError):
        violations.append("INV-10")

    # INV-11: encrypted reasoning never reaches a public-candidate field.
    secrets = [r.encrypted_value for r in conv.reasoning if r.encrypted_value]
    if secrets:
        public = json.dumps(
            [
                [(m.content, m.reasoning) for m in conv.messages],
                [(c.args_text, c.result) for c in conv.tool_calls],
                [repr(e.value) for e in conv.custom_events],
                conv.shared_state,
            ],
            default=repr,
        )
        if any(secret in public for secret in secrets):
            violations.append("INV-11")

    return violations


def check_invariants(conv: ConversationState) -> None:
    """Fail the calling test if ``conv`` violates any invariant."""
    violations = find_violations(conv)
    assert not violations, f"invariants violated: {', '.join(violations)}"
