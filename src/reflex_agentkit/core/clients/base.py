"""Client protocols and validated event decoding (API §7.1-7.2).

``AGUIAgent`` is what adapters implement (they yield AG-UI events for a run input);
``AgentClient`` is what ``AgentState`` consumes. Both are runtime-checkable, so
``AgentState.agent`` can hold either (``AgentSource``). Clients validate every event
with :func:`validate_event`, which skips and logs anything invalid (REQ-012.2-3).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Protocol, TypeAlias, runtime_checkable

from ag_ui.core import BaseEvent, RunAgentInput

from reflex_agentkit.core.models import Diagnostic
from reflex_agentkit.core.reducer import parse_event

__all__ = ["AGUIAgent", "AgentClient", "AgentSource", "validate_event"]

logger = logging.getLogger("reflex_agentkit.core.clients")

_LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING}


@runtime_checkable
class AGUIAgent(Protocol):
    """An in-process agent that yields AG-UI events for a run (API §7.1)."""

    def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        """Yield the run's events, from ``RUN_STARTED`` to one terminal event."""
        ...


@runtime_checkable
class AgentClient(Protocol):
    """The transport ``AgentState`` streams from (API §7.2)."""

    def stream(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        """Yield validated events; raise ``AgentHTTPError``/``AgentStreamError`` on failure."""
        ...

    async def aclose(self) -> None:
        """Release pooled resources. Idempotent."""
        ...


AgentSource: TypeAlias = AgentClient | AGUIAgent
"""What ``AgentState.agent`` accepts; an ``AGUIAgent`` is wrapped in-process."""


def validate_event(raw: object) -> BaseEvent | None:
    """Validate a wire dict or an event object; ``None`` (logged) if it must be skipped.

    Event objects are re-validated through their camelCase dump, so events built with
    ``model_construct`` cannot bypass the schema (REQ-012.3).
    """
    if isinstance(raw, BaseEvent):
        try:
            raw = raw.model_dump(mode="json", by_alias=True, exclude_none=True, warnings=False)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            logger.warning(
                "skipped an AG-UI event that cannot be serialized: %s", type(exc).__name__
            )
            return None
    result = parse_event(raw)
    if isinstance(result, Diagnostic):
        logger.log(_LEVELS.get(result.level, logging.WARNING), "%s", result.message)
        return None
    return result
