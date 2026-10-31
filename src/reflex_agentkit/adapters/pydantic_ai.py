"""PydanticAI → AG-UI adapter (API §7.5, TD DD-011). Needs ``reflex-agentkit[pydantic-ai]``."""

from __future__ import annotations

from reflex_agentkit.adapters._require import require

require("pydantic-ai", "pydantic_ai", "pydantic_ai.ui.ag_ui")

import inspect  # noqa: E402 - the guard must run before the optional imports
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence  # noqa: E402
from typing import Any  # noqa: E402

from ag_ui.core import BaseEvent, RunAgentInput  # noqa: E402
from pydantic_ai import DeferredToolRequests  # noqa: E402
from pydantic_ai.agent import AbstractAgent  # noqa: E402
from pydantic_ai.ui.ag_ui import AGUIAdapter  # noqa: E402

from reflex_agentkit.core.errors import ConfigurationError  # noqa: E402

__all__ = ["PydanticAIAgent"]

DepsFactory = Callable[[RunAgentInput], Any | Awaitable[Any]]


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
        run_kwargs: Forwarded to ``AGUIAdapter.run_stream`` (``model_settings``,
            ``usage_limits``, ``model``, ...).
    """

    def __init__(
        self,
        agent: AbstractAgent[Any, Any],
        *,
        deps: Any = None,
        deps_factory: DepsFactory | None = None,
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
