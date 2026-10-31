"""Run Reflex event handlers in process, without a browser or an app (T-024, TD OQ-1).

Reflex 0.10.1 ships the machinery the server itself uses: a
``BaseStateEventProcessor`` configured with a ``StateManagerMemory`` processes events for
any token, runs foreground handlers under the state lock, runs background handlers as
tasks whose ``async with self`` re-acquires the lock, and emits deltas through the
``event_namespace`` it is given. The harness wires those pieces together::

    async with ReflexHarness() as rx_:
        await rx_.call("tok", MyState, "send_message", text="hi")   # waits for the chain
        state = await rx_.state("tok", MyState)

``call`` waits for the whole chain (``EventFuture.wait_all``), including background
events the handler returned, and re-raises any exception raised along the chain.
``start`` enqueues without waiting. Background-task exceptions are collected in
``errors`` (the processor's backend exception handler), and ``deltas`` records every
``(token, delta)`` sent to the "browser".
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar, cast

import pytest
import reflex as rx
from reflex.istate.manager import StateManager
from reflex.istate.manager.memory import StateManagerMemory
from reflex.istate.manager.token import BaseStateToken
from reflex_base.event import Event
from reflex_base.event.processor import BaseStateEventProcessor, EventFuture

if TYPE_CHECKING:
    from reflex.app import EventNamespace

S = TypeVar("S", bound=rx.State)


class _Namespace:
    """Stands in for the Socket.IO namespace: records the deltas sent to clients."""

    def __init__(self, sink: list[tuple[str, Mapping[str, Any]]]) -> None:
        self._sink = sink

    async def emit_update(self, update: Any, token: str) -> None:
        if update.delta:
            self._sink.append((token, update.delta))


class ReflexHarness:
    """An event processor over a state manager, driven from tests."""

    def __init__(self, state_manager: StateManager | None = None) -> None:
        # mypy sees StateManagerMemory as abstract (Reflex's overloads); it is concrete.
        self.manager: StateManager = state_manager or StateManagerMemory()  # type: ignore[abstract]
        self.deltas: list[tuple[str, Mapping[str, Any]]] = []
        self.errors: list[Exception] = []
        self._raised: set[int] = set()  # ids of exceptions ``call`` already re-raised
        self.processor = BaseStateEventProcessor(backend_exception_handler=self._on_error)
        namespace = cast("EventNamespace", _Namespace(self.deltas))  # duck-typed stand-in
        self.processor.configure(state_manager=self.manager, event_namespace=namespace)

    def _on_error(self, exc: Exception) -> None:
        self.errors.append(exc)

    async def __aenter__(self) -> ReflexHarness:
        await self.processor.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.processor.stop()

    async def start(
        self, token: str, state_cls: type[rx.State], handler: str, **payload: Any
    ) -> EventFuture:
        """Enqueue ``state_cls.handler(**payload)`` for ``token``; return its future."""
        event = Event(name=f"{state_cls.get_full_name()}.{handler}", payload=payload)
        return await self.processor.enqueue(token, event)

    async def call(
        self,
        token: str,
        state_cls: type[rx.State],
        handler: str,
        *,
        wait_s: float = 5.0,
        **payload: Any,
    ) -> None:
        """Run the handler and everything it chains (background tasks included).

        A foreground handler's exception is re-raised by its future. A background
        handler's exception never reaches the future (``wait_all`` suppresses child
        failures); the processor reports it to ``errors``, and it is re-raised here too.
        """
        future = await self.start(token, state_cls, handler, **payload)
        try:
            await asyncio.wait_for(future.wait_all(), wait_s)
        except Exception as exc:
            self._raised.add(id(exc))  # the processor reports it again later
            raise
        await asyncio.sleep(0)  # let the processor report finished background tasks
        for error in self.errors:
            if id(error) not in self._raised:
                self._raised.add(id(error))
                raise error

    async def state(self, token: str, state_cls: type[S]) -> S:
        """The current substate of ``state_cls`` for ``token`` (read-only use)."""
        root = await self.manager.get_state(BaseStateToken(ident=token, cls=state_cls))
        return root.get_substate(state_cls.get_full_name().split("."))  # type: ignore[return-value]

    def deltas_for(self, token: str) -> list[Mapping[str, Any]]:
        return [delta for t, delta in self.deltas if t == token]


@pytest.fixture
async def reflex_harness() -> AsyncIterator[ReflexHarness]:
    """A started harness over a fresh in-memory state manager."""
    async with ReflexHarness() as harness:
        yield harness
