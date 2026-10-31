"""An in-memory ``StateAccess`` for driver tests (T-025, TD §5.2).

It stores one conversation, counts lock sections and publishes, and records every
published conversation. Tests can replace ``conv`` (as ``new_thread`` or a state reset
would) or set ``cancel_requested`` (as a ``cancel_run`` on another worker would).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.state._driver import StateView


class FakeStateAccess:
    """A counting, recording stand-in for ``AgentState``'s lock and projection."""

    def __init__(
        self,
        conv: ConversationState,
        *,
        client_token: str = "tok",  # noqa: S107 - a Reflex session id, not a secret
    ) -> None:
        self.conv = conv
        self.cancel_requested = ""
        self.client_token = client_token
        self.published: list[ConversationState] = []
        self.publish_times: list[float] = []
        self.lock_sections = 0
        self.first_publish = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def publishes(self) -> int:
        return len(self.published)

    def _publish(self, conv: ConversationState) -> None:
        self.conv = conv
        self.published.append(conv)
        self.publish_times.append(time.monotonic())
        self.first_publish.set()

    @asynccontextmanager
    async def locked(self) -> AsyncIterator[StateView]:
        async with self._lock:
            self.lock_sections += 1
            yield StateView(
                conv=self.conv,
                cancel_requested=self.cancel_requested,
                client_token=self.client_token,
                publish=self._publish,
            )
