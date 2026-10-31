"""``RunInputBuilder``: ``ConversationState`` -> ``RunAgentInput`` (DM §7.3, API §8.1).

The full history is sent on every run. Reasoning records go back immediately before
their assistant message with their encrypted value (REQ-011.2); unlinked records are
appended at the end. Assistant messages carry their tool calls with the current (possibly
edited) arguments. ``resume`` is present only when the run answers interrupts.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence

from ag_ui.core import (
    AssistantMessage,
    DeveloperMessage,
    FunctionCall,
    Message,
    ReasoningMessage,
    RunAgentInput,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from ag_ui.core import ToolCall as AguiToolCall

from reflex_agentkit.core.commands import resume_entries
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import ChatMessage, MessageRole, ReasoningRecord
from reflex_agentkit.core.tools import ClientTool

__all__ = ["PROTOCOL_VERSION", "RunInputBuilder", "to_agui_messages"]

PROTOCOL_VERSION = "1.0"


def _reasoning(record: ReasoningRecord) -> ReasoningMessage | None:
    if not record.content and record.encrypted_value is None:
        return None
    return ReasoningMessage(
        id=record.id, content=record.content, encrypted_value=record.encrypted_value
    )


def _assistant(conv: ConversationState, msg: ChatMessage) -> AssistantMessage:
    calls = []
    for call_id in msg.tool_call_ids:
        index = conv._tool_index.get(call_id)
        if index is None:  # pragma: no cover - excluded by INV-3
            continue
        call = conv.tool_calls[index]
        arguments = json.dumps(call.args or {})
        calls.append(
            AguiToolCall(id=call.id, function=FunctionCall(name=call.name, arguments=arguments))
        )
    return AssistantMessage(id=msg.id, content=msg.content or None, tool_calls=calls or None)


def _message(conv: ConversationState, msg: ChatMessage) -> Message:
    match msg.role:
        case MessageRole.USER:
            return UserMessage(id=msg.id, content=msg.content)
        case MessageRole.SYSTEM:
            return SystemMessage(id=msg.id, content=msg.content)
        case MessageRole.DEVELOPER:
            return DeveloperMessage(id=msg.id, content=msg.content)
        case MessageRole.ASSISTANT:
            return _assistant(conv, msg)
    return ToolMessage(
        id=msg.id,
        content=msg.content,
        tool_call_id=msg.tool_call_id or "",
        error=msg.content if msg.is_error else None,
    )


def to_agui_messages(conv: ConversationState) -> list[Message]:
    """The conversation history as AG-UI messages (DM §7.3)."""
    by_assistant: dict[str, list[ReasoningRecord]] = {}
    loose: list[ReasoningRecord] = []
    message_ids = conv._message_index
    for record in conv.reasoning:
        if record.assistant_message_id in message_ids:
            by_assistant.setdefault(record.assistant_message_id, []).append(record)
        else:
            loose.append(record)

    out: list[Message] = []
    for msg in conv.messages:
        for record in by_assistant.get(msg.id, ()):
            if (reasoning := _reasoning(record)) is not None:
                out.append(reasoning)
        out.append(_message(conv, msg))
    out.extend(r for record in loose if (r := _reasoning(record)) is not None)
    return out


@dataclasses.dataclass(frozen=True, slots=True)
class RunInputBuilder:
    """Builds the ``RunAgentInput`` of a run (API §8.1).

    Args:
        client_tools: The tools advertised in ``tools`` (REQ-018.1).
    """

    client_tools: Sequence[ClientTool] = ()

    def build(self, conv: ConversationState) -> RunAgentInput:
        """The input for the run that ``begin_run`` started on ``conv``."""
        resume = resume_entries(conv)
        return RunAgentInput(
            thread_id=conv.thread_id,
            run_id=conv.run_id,
            protocol_version=PROTOCOL_VERSION,
            state=conv.shared_state,
            messages=to_agui_messages(conv),
            tools=[tool.to_agui_tool() for tool in self.client_tools],
            context=[],
            forwarded_props={},
            resume=resume or None,
        )
