"""``InProcessAGUIClient``: run an ``AGUIAgent`` in the current event loop (API §7.3).

No HTTP and no serialization: the agent's event objects are validated and passed on
(REQ-021.5). Cancelling the consumer cancels the agent, which observes
``CancelledError`` (REQ-007.3). An exception raised by the agent becomes
``AgentStreamError(reason="agent_raised")`` with the original as ``__cause__``; its
message names only the exception type, since agent errors may quote secrets.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from ag_ui.core import BaseEvent, EventType, RunAgentInput

from reflex_agentkit.core.clients.base import AGUIAgent, validate_event
from reflex_agentkit.core.errors import AgentStreamError, ConfigurationError

__all__ = ["InProcessAGUIClient"]

_TERMINAL = frozenset({EventType.RUN_FINISHED, EventType.RUN_ERROR})


class InProcessAGUIClient:
    """Wraps an in-process ``AGUIAgent`` as an ``AgentClient`` (REQ-021.5).

    Safe to share across sessions as long as the agent is: it keeps no per-run state.
    """

    def __init__(self, agent: AGUIAgent) -> None:
        if not isinstance(agent, AGUIAgent):
            raise ConfigurationError(
                f"InProcessAGUIClient needs an AGUIAgent (an object with run()), "
                f"got {type(agent).__name__}"
            )
        self._agent = agent

    def __repr__(self) -> str:
        return f"{type(self).__name__}(agent={type(self._agent).__name__})"

    async def stream(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        """Yield the agent's validated events until a terminal one."""
        iterator = self._agent.run(run_input)
        try:
            while True:
                try:
                    raw = await anext(iterator)
                except StopAsyncIteration:
                    break
                except Exception as exc:
                    raise AgentStreamError(
                        "agent_raised", f"the agent raised {type(exc).__name__}"
                    ) from exc
                event = validate_event(raw)
                if event is None:
                    continue
                yield event
                if event.type in _TERMINAL:
                    return
        finally:
            closer = getattr(iterator, "aclose", None)  # plain async iterators lack it
            if closer is not None:
                await closer()
        raise AgentStreamError("eof", "the agent's event stream ended unexpectedly")

    async def aclose(self) -> None:
        """Nothing to release; present for the ``AgentClient`` protocol. Idempotent."""
