"""LangGraph → AG-UI adapter (API §7.6, TD DD-012). Needs ``reflex-agentkit[langgraph]``.

``LangGraphAGUIAgent`` subclasses the official ``ag_ui_langgraph.LangGraphAgent`` with
AG-UI standard interrupts on. ``request_tool_approval`` is called inside a graph node or
tool to pause for a human decision on a tool call, with the same payload contract as the
PydanticAI adapter (API §7.4).
"""

from __future__ import annotations

from reflex_agentkit.adapters._require import require

require("langgraph", "langgraph", "ag_ui_langgraph")

import dataclasses  # noqa: E402 - the guard must run before the optional imports
import json  # noqa: E402
import logging  # noqa: E402
from collections.abc import AsyncIterator, Mapping  # noqa: E402
from typing import Any, Self, cast  # noqa: E402

from ag_ui.core import (  # noqa: E402
    BaseEvent,
    CustomEvent,
    Interrupt,
    ResumeEntry,
    RunAgentInput,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
)
from ag_ui_langgraph import LangGraphAgent  # noqa: E402
from ag_ui_langgraph.interrupts import (  # noqa: E402
    DEFAULT_RESUME_SENTINEL_CANCELLED,
    lg_interrupt_to_agui,
)
from langchain_core.runnables import RunnableConfig  # noqa: E402
from langgraph.graph.state import CompiledStateGraph  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402
from langgraph.types import Interrupt as LangGraphInterrupt  # noqa: E402

from reflex_agentkit.adapters._edits import with_edited_args_notice  # noqa: E402
from reflex_agentkit.core.errors import ConfigurationError  # noqa: E402

__all__ = ["ApprovalDecision", "LangGraphAGUIAgent", "request_tool_approval"]

APPROVAL_REASON = "tool_call"
"""The interrupt reason that marks a tool approval (API §7.6)."""

APPROVAL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "approved": {"type": "boolean"},
        "editedArgs": {"type": "object"},
        "reason": {"type": "string"},
    },
    "required": ["approved"],
}
"""The JSON Schema of an approval answer; the same one PydanticAI sends (API §7.4)."""

CANCELLED_APPROVAL: dict[str, Any] = {"approved": False, "reason": "cancelled"}
"""What a cancelled tool approval resumes with (DD-012)."""

_HIDDEN_SNAPSHOT_KEYS = frozenset({"messages", "tools"})
_LEGACY_EVENT = "on_interrupt"
_LEGACY_PREFIX = "legacy-"
_LEGACY_TOOL_PREFIX = "legacy-tool-"

_log = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """A human decision on a tool call (API §7.6).

    Attributes:
        approved: Whether the tool may run.
        args: The arguments to run it with: the edited ones when the user edited them,
            otherwise the original ones.
        reason: The rejection reason, ``"cancelled"`` when the run was cancelled while
            waiting, or ``None``.
        edited: Whether the user approved with arguments that differ from the proposed
            ones (REQ-035.2, REQ-035.5).
    """

    approved: bool
    args: dict[str, Any]
    reason: str | None = None
    edited: bool = False

    def tool_result(self, result: Any) -> Any:
        """The result to give the model: with the edited-arguments notice when ``edited``.

        Use it to build the ``ToolMessage`` so the model knows the user changed the
        arguments on purpose (REQ-035.2). Without edits ``result`` comes back unchanged.
        """
        if not self.edited:
            return result
        text = with_edited_args_notice(result, self.args)
        _log.debug("edited-arguments notice: %s", text)
        return text


def request_tool_approval(
    tool_call_id: str, tool_name: str, args: dict[str, Any], *, message: str | None = None
) -> ApprovalDecision:
    """Pause the graph until the user approves, edits or rejects a tool call (REQ-034.3).

    Call it inside a graph node or tool. It raises LangGraph's ``interrupt`` with the
    keys that ag-ui-langgraph maps onto the AG-UI ``Interrupt``, so the call shows as a
    ``pending_approval`` tool card. When the graph resumes, it returns the decision.

    Args:
        tool_call_id: The ID of the tool call in the assistant message.
        tool_name: The tool's name.
        args: The tool call's arguments.
        message: The question shown to the user; defaults to ``"Approve <tool_name>?"``.
    """
    answer = interrupt(
        {
            "reason": APPROVAL_REASON,
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "args": args,
            "message": message if message is not None else f"Approve {tool_name}?",
            "responseSchema": APPROVAL_RESPONSE_SCHEMA,
        }
    )
    return _decision(answer, args)


def _decision(answer: Any, args: dict[str, Any]) -> ApprovalDecision:
    """Read the API §7.4 payload. Anything but ``approved: true`` is a rejection."""
    if not isinstance(answer, Mapping):
        return ApprovalDecision(approved=False, args=args)
    reason = answer.get("reason")
    reason = reason if isinstance(reason, str) else None
    if answer.get("approved") is not True:
        return ApprovalDecision(approved=False, args=args, reason=reason)
    edited = answer.get("editedArgs")
    if not isinstance(edited, Mapping) or dict(edited) == args:
        return ApprovalDecision(approved=True, args=args)
    return ApprovalDecision(approved=True, args=dict(edited), edited=True)


class LangGraphAGUIAgent(LangGraphAgent):  # type: ignore[misc]  # untyped upstream base
    """Run a compiled LangGraph graph as an ``AGUIAgent`` (REQ-034.1).

    One instance can serve every session: each ``run()`` works on a fresh clone, because
    the upstream agent keeps per-run state on the instance (DD-012).

    Args:
        graph: A compiled graph with a checkpointer (REQ-034.4).
        name: The agent name reported to AG-UI.
        config: The base ``RunnableConfig`` for every run.
        legacy_interrupts: Read interrupts from the legacy ``on_interrupt`` CUSTOM event
            and resume through ``forwarded_props`` (REQ-034.5, compatibility mode).

    Raises:
        ConfigurationError: ``graph`` is not a compiled graph, or it has no checkpointer.
    """

    def __init__(
        self,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        *,
        name: str = "agent",
        config: RunnableConfig | None = None,
        legacy_interrupts: bool = False,
    ) -> None:
        if not isinstance(graph, CompiledStateGraph):
            raise ConfigurationError(
                f"LangGraphAGUIAgent needs a compiled graph, not {type(graph).__name__}"
            )
        if graph.checkpointer is None:
            raise ConfigurationError(
                "LangGraphAGUIAgent needs a graph compiled with a checkpointer, "
                "for example graph.compile(checkpointer=InMemorySaver())"
            )
        self.legacy_interrupts = legacy_interrupts
        super().__init__(
            name=name,
            graph=graph,
            config=config,
            emit_interrupt_outcome=not legacy_interrupts,
            enable_legacy_on_interrupt_event=legacy_interrupts,
            emit_raw_events=False,
        )

    def __repr__(self) -> str:
        return f"LangGraphAGUIAgent(name={self.name!r})"

    def clone(self) -> Self:
        """A fresh copy with clean per-run state and the same settings."""
        return type(self)(
            self.graph,
            name=self.name,
            config=cast(RunnableConfig, dict(self.config)) if self.config else None,
            legacy_interrupts=self.legacy_interrupts,
        )

    async def run(self, input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        """Stream one run as AG-UI events on a fresh clone (API §7.1)."""
        worker = self.clone()
        if not self.legacy_interrupts:
            async for event in LangGraphAgent.run(worker, input):
                yield event
            return
        legacy_values: list[Any] = []
        async for event in LangGraphAgent.run(worker, _legacy_input(input)):
            if isinstance(event, CustomEvent) and event.name == _LEGACY_EVENT:
                legacy_values.append(_decode(event.value))
                continue
            if isinstance(event, RunFinishedEvent) and event.outcome is None and legacy_values:
                event = _legacy_finish(event, legacy_values)
            yield event

    def get_state_snapshot(self, state: Any) -> Any:
        """The upstream snapshot without ``messages`` and ``tools`` (DD-012)."""
        snapshot = super().get_state_snapshot(state)
        if not isinstance(snapshot, Mapping):
            return snapshot
        return {k: v for k, v in snapshot.items() if k not in _HIDDEN_SNAPSHOT_KEYS}

    def _build_command_from_agui_resume(
        self,
        entries: list[ResumeEntry],
        *,
        open_interrupts: list[Interrupt] | None = None,
    ) -> Command[Any]:
        """Native LangGraph resumes (DD-012).

        One entry resumes with its payload; several use ``{interrupt_id: payload}`` so each
        interrupted node gets its own answer. A cancelled tool approval resumes as a
        rejection with reason ``"cancelled"``; a cancelled generic interrupt keeps the
        upstream ``__agui_cancelled__`` sentinel.
        """
        reasons = {i.id: i.reason for i in open_interrupts or ()}

        def answer(entry: ResumeEntry) -> Any:
            if entry.status == "resolved":
                return entry.payload
            is_approval = reasons.get(entry.interrupt_id) == APPROVAL_REASON
            return _cancelled_answer(entry.interrupt_id, is_approval=is_approval)

        if len(entries) == 1:
            return Command(resume=answer(entries[0]))
        return Command(resume={entry.interrupt_id: answer(entry) for entry in entries})


# --- legacy interrupts (REQ-034.5, DD-012) ---------------------------------------------------


def _cancelled_answer(interrupt_id: str, *, is_approval: bool) -> Any:
    if is_approval:
        return dict(CANCELLED_APPROVAL)
    return {DEFAULT_RESUME_SENTINEL_CANCELLED: True, "interrupt_id": interrupt_id}


def _legacy_input(run_input: RunAgentInput) -> RunAgentInput:
    """Move a ``resume[]`` answer to ``forwarded_props.command.resume`` (DD-012)."""
    if not run_input.resume:
        return run_input
    entry = run_input.resume[0]
    if entry.status == "resolved":
        answer = entry.payload
    else:
        is_approval = entry.interrupt_id.startswith(_LEGACY_TOOL_PREFIX)
        answer = _cancelled_answer(entry.interrupt_id, is_approval=is_approval)
    forwarded = dict(run_input.forwarded_props or {})
    forwarded["command"] = {"resume": answer}
    return run_input.model_copy(update={"resume": None, "forwarded_props": forwarded})


def _decode(value: Any) -> Any:
    """The legacy event carries a dict value as JSON text and a string as itself."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def _legacy_finish(event: RunFinishedEvent, values: list[Any]) -> RunFinishedEvent:
    """``RUN_FINISHED`` with the first legacy interrupt as a standard outcome."""
    if len(values) > 1:
        _log.warning("legacy interrupts: dropped %d extra interrupt(s)", len(values) - 1)
    value = values[0]
    is_approval = isinstance(value, Mapping) and value.get("reason") == APPROVAL_REASON
    prefix = _LEGACY_TOOL_PREFIX if is_approval else _LEGACY_PREFIX
    mapped = lg_interrupt_to_agui(LangGraphInterrupt(value=value, id=f"{prefix}{event.run_id}"))
    mapped = mapped.model_copy(update={"metadata": {"langgraph": {"raw": value}}})
    outcome = RunFinishedInterruptOutcome(type="interrupt", interrupts=[mapped])
    return event.model_copy(update={"outcome": outcome})
