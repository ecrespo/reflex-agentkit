"""PydanticAI → AG-UI adapter (API §7.5, TD DD-011). Needs ``reflex-agentkit[pydantic-ai]``."""

from __future__ import annotations

from reflex_agentkit.adapters._require import require

require("pydantic-ai", "pydantic_ai", "pydantic_ai.ui.ag_ui")

import dataclasses  # noqa: E402 - the guard must run before the optional imports
import inspect  # noqa: E402
import logging  # noqa: E402
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence  # noqa: E402
from typing import Any  # noqa: E402

from ag_ui.core import BaseEvent, RunAgentInput  # noqa: E402
from pydantic_ai import DeferredToolRequests, RunContext  # noqa: E402
from pydantic_ai.agent import AbstractAgent  # noqa: E402
from pydantic_ai.capabilities import AbstractCapability  # noqa: E402
from pydantic_ai.exceptions import UserError  # noqa: E402
from pydantic_ai.messages import ToolCallPart  # noqa: E402
from pydantic_ai.tools import ToolDefinition  # noqa: E402
from pydantic_ai.ui.ag_ui import AGUIAdapter  # noqa: E402
from pydantic_ai.ui.ag_ui._interrupt import interrupt_id_to_tool_call_id  # noqa: E402

from reflex_agentkit.adapters._edits import with_edited_args_notice  # noqa: E402
from reflex_agentkit.core.errors import ConfigurationError  # noqa: E402

__all__ = ["PydanticAIAgent"]

DepsFactory = Callable[[RunAgentInput], Any | Awaitable[Any]]

_log = logging.getLogger(__name__)


class PydanticAIAgent:
    """Run a PydanticAI agent as an ``AGUIAgent`` (REQ-022.1).

    Approval-required tools pause with an AG-UI interrupt with no configuration: when
    the agent's ``output_type`` lacks ``DeferredToolRequests`` it is added for the run
    (DD-011). Resumes follow PydanticAI's native payload contract (API §7.4).

    Args:
        agent: The PydanticAI agent.
        deps: Dependencies passed to every run.
        deps_factory: Builds the dependencies of one run from its input (sync or async).
            Mutually exclusive with ``deps``.
        notify_edited_args: Tell the model when the user approved a tool call with
            edited arguments, by appending a notice to the tool's result (REQ-035.1,
            REQ-035.4).
        run_kwargs: Forwarded to ``AGUIAdapter.run_stream`` (``model_settings``,
            ``usage_limits``, ``model``, ...).
    """

    def __init__(
        self,
        agent: AbstractAgent[Any, Any],
        *,
        deps: Any = None,
        deps_factory: DepsFactory | None = None,
        notify_edited_args: bool = True,
        **run_kwargs: Any,
    ) -> None:
        if not isinstance(agent, AbstractAgent):
            raise ConfigurationError(
                f"PydanticAIAgent needs a pydantic_ai Agent, not {type(agent).__name__}"
            )
        if deps is not None and deps_factory is not None:
            raise ConfigurationError("PydanticAIAgent takes deps or deps_factory, not both")
        self._agent = agent
        self._deps = deps
        self._deps_factory = deps_factory
        self._run_kwargs = run_kwargs
        self._notify_edited_args = notify_edited_args
        self._output_type = _with_deferred(agent.output_type)

    def __repr__(self) -> str:
        return f"PydanticAIAgent({self._agent.name or type(self._agent).__name__!s})"

    async def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        """Stream one run as AG-UI events (API §7.1)."""
        deps = self._deps
        if self._deps_factory is not None:
            deps = self._deps_factory(run_input)
            if inspect.isawaitable(deps):
                deps = await deps
        kwargs = dict(self._run_kwargs)
        if self._output_type is not None:
            kwargs.setdefault("output_type", self._output_type)
        edits = _edited_calls(run_input) if self._notify_edited_args else {}
        if edits:
            kwargs["capabilities"] = [*(kwargs.get("capabilities") or ()), _EditNotice(edits)]
        adapter = AGUIAdapter(agent=self._agent, run_input=run_input)
        stream = adapter.run_stream(deps=deps, **kwargs)
        try:
            async for event in stream:
                yield event
        finally:
            closer = getattr(stream, "aclose", None)
            if closer is not None:
                await closer()


def _with_deferred(output_type: Any) -> list[Any] | None:
    """``[*output types, DeferredToolRequests]``, or ``None`` if it is already there."""
    if isinstance(output_type, Sequence) and not isinstance(output_type, str | bytes):
        types = list(output_type)
    else:
        types = [output_type]
    if any(t is DeferredToolRequests for t in types):
        return None
    return [*types, DeferredToolRequests]


def _edited_calls(run_input: RunAgentInput) -> dict[str, dict[str, Any]]:
    """Tool call ID → edited arguments, for every approval resumed with ``editedArgs``."""
    edits: dict[str, dict[str, Any]] = {}
    for entry in run_input.resume or ():
        payload = entry.payload
        if entry.status != "resolved" or not isinstance(payload, Mapping):
            continue
        edited = payload.get("editedArgs")
        if payload.get("approved") is not True or not isinstance(edited, Mapping):
            continue
        try:
            call_id = interrupt_id_to_tool_call_id(entry.interrupt_id)
        except UserError:  # not one of PydanticAI's approval interrupts
            continue
        edits[call_id] = dict(edited)
    return edits


@dataclasses.dataclass
class _EditNotice(AbstractCapability[Any]):
    """Append the edited-arguments notice to the results of edited calls (DD-013)."""

    edits: dict[str, dict[str, Any]]

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: Any,
        result: Any,
    ) -> Any:
        edited = self.edits.get(call.tool_call_id)
        if edited is None:
            return result
        text = with_edited_args_notice(result, edited)
        _log.debug("edited-arguments notice: %s", text)
        return text
