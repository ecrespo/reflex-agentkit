"""The run driver and its port to Reflex (TD §3.3 Flows A-E, §5.2).

``StateAccess`` is the driver's only way to touch the Reflex state: ``locked()`` holds
the session's state lock and yields a :class:`StateView` with the stored conversation,
the pending cancel request and a ``publish`` that writes the conversation back and
projects it onto the public vars. ``AgentState`` implements it over ``async with self``;
tests use an in-memory fake, so the driver is tested without Reflex.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from reflex_agentkit.core.conversation import ConversationState

__all__ = ["StateAccess", "StateView"]


@dataclasses.dataclass(frozen=True, slots=True)
class StateView:
    """What the driver sees while it holds the state lock.

    Attributes:
        conv: The conversation stored in the session's state.
        cancel_requested: The run ID that ``cancel_run`` asked to stop (``""`` if none).
        client_token: The Reflex client token of the session.
        publish: Store a conversation and project it onto the public vars.
    """

    conv: ConversationState
    cancel_requested: str
    client_token: str
    publish: Callable[[ConversationState], None]


class StateAccess(Protocol):
    """The driver's port to the session state (TD §5.2)."""

    def locked(self) -> AbstractAsyncContextManager[StateView]:
        """Hold the state lock for the duration of the ``async with`` block."""
        ...
