"""``InProcessAGUIClient`` (T-023, API §7.3, REQ-021.5, REQ-007.3)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from ag_ui.core import (
    BaseEvent,
    EventType,
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageChunkEvent,
    TextMessageContentEvent,
)

from reflex_agentkit.core.clients.base import AgentClient
from reflex_agentkit.core.clients.in_process import InProcessAGUIClient
from reflex_agentkit.core.errors import AgentStreamError, ConfigurationError

RUN_INPUT = RunAgentInput(
    thread_id="t", run_id="r", state={}, messages=[], tools=[], context=[], forwarded_props={}
)


class ScriptedAgent:
    """Yields ``events``; then raises ``error`` or waits forever when asked to."""

    def __init__(
        self,
        events: list[BaseEvent],
        *,
        error: Exception | None = None,
        wait_forever: bool = False,
    ) -> None:
        self.events = events
        self.error = error
        self.wait_forever = wait_forever
        self.inputs: list[RunAgentInput] = []
        self.saw_cancelled = False
        self.cleaned_up = False

    async def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        self.inputs.append(run_input)
        try:
            for event in self.events:
                yield event
            if self.error is not None:
                raise self.error
            if self.wait_forever:
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.saw_cancelled = True
            raise
        finally:
            self.cleaned_up = True


STARTED = RunStartedEvent(thread_id="t", run_id="r")
FINISHED = RunFinishedEvent(thread_id="t", run_id="r")


async def _collect(client: InProcessAGUIClient) -> list[BaseEvent]:
    return [event async for event in client.stream(RUN_INPUT)]


async def test_REQ_021_5_yields_the_agents_events() -> None:
    """REQ-021.5: events come straight from the agent object, validated."""
    agent = ScriptedAgent([STARTED, TextMessageChunkEvent(message_id="m", delta="hi"), FINISHED])
    client = InProcessAGUIClient(agent)
    events = await _collect(client)
    assert [e.type for e in events] == [
        EventType.RUN_STARTED,
        EventType.TEXT_MESSAGE_CHUNK,
        EventType.RUN_FINISHED,
    ]
    assert agent.inputs == [RUN_INPUT]
    assert agent.cleaned_up


def test_REQ_021_5_is_an_agent_client_and_needs_an_agent() -> None:
    """REQ-021.1, REQ-021.5: it is an ``AgentClient``; it wraps only ``AGUIAgent``s."""
    assert isinstance(InProcessAGUIClient(ScriptedAgent([])), AgentClient)
    with pytest.raises(ConfigurationError):
        InProcessAGUIClient(object())  # type: ignore[arg-type]


async def test_REQ_012_3_invalid_events_are_skipped() -> None:
    """REQ-012.3: an invalid event object is skipped, not raised."""
    bad = TextMessageContentEvent.model_construct(delta="x")
    events = await _collect(InProcessAGUIClient(ScriptedAgent([STARTED, bad, FINISHED])))
    assert [e.type for e in events] == [EventType.RUN_STARTED, EventType.RUN_FINISHED]


async def test_REQ_021_5_stops_after_a_terminal_event_and_closes_the_agent() -> None:
    """API §7.2: after the terminal event the agent's iterator is closed."""
    agent = ScriptedAgent([STARTED, FINISHED], wait_forever=True)
    events = await asyncio.wait_for(_collect(InProcessAGUIClient(agent)), 1)
    assert len(events) == 2
    assert agent.cleaned_up


async def test_REQ_007_3_cancellation_reaches_the_agent() -> None:
    """REQ-007.3: cancelling the consumer cancels the agent, which sees ``CancelledError``."""
    agent = ScriptedAgent([STARTED], wait_forever=True)
    client = InProcessAGUIClient(agent)
    first = asyncio.Event()

    async def consume() -> None:
        async for _ in client.stream(RUN_INPUT):
            first.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first.wait(), 1)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert agent.saw_cancelled
    assert agent.cleaned_up


async def test_REQ_007_3_closing_the_iterator_closes_the_agent() -> None:
    """API §7.2: ``aclose()`` on the iterator releases the agent's resources."""
    agent = ScriptedAgent([STARTED], wait_forever=True)
    stream = InProcessAGUIClient(agent).stream(RUN_INPUT)
    await anext(stream)
    await stream.aclose()  # type: ignore[attr-defined]
    assert agent.cleaned_up


async def test_REQ_021_5_agent_exceptions_become_stream_errors() -> None:
    """API §7.3: ``AgentStreamError(reason="agent_raised")`` with the original as cause."""
    original = RuntimeError("model quota exceeded for key sk-SECRET")
    agent = ScriptedAgent([STARTED], error=original)
    with pytest.raises(AgentStreamError) as info:
        await _collect(InProcessAGUIClient(agent))
    assert info.value.reason == "agent_raised"
    assert info.value.__cause__ is original
    assert "RuntimeError" in str(info.value)
    assert "sk-SECRET" not in str(info.value)


async def test_REQ_004_4_agent_ending_without_a_terminal_event_is_an_error() -> None:
    """REQ-004.4: the agent's stream ending early is reported like an HTTP EOF."""
    with pytest.raises(AgentStreamError) as info:
        await _collect(InProcessAGUIClient(ScriptedAgent([STARTED])))
    assert info.value.reason == "eof"


async def test_REQ_021_5_aclose_is_idempotent() -> None:
    """API §7.2: ``aclose`` holds nothing to release and can be called twice."""
    client = InProcessAGUIClient(ScriptedAgent([]))
    await client.aclose()
    await client.aclose()


class _PlainIterator:
    """An async iterator without ``aclose`` (not an async generator)."""

    def __init__(self, events: list[BaseEvent]) -> None:
        self._events = iter(events)

    def __aiter__(self) -> _PlainIterator:
        return self

    async def __anext__(self) -> BaseEvent:
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None


class _PlainAgent:
    def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        return _PlainIterator([STARTED, FINISHED])


async def test_REQ_021_5_plain_async_iterators_are_supported() -> None:
    """API §7.1: ``run`` may return any async iterator, not only an async generator."""
    client = InProcessAGUIClient(_PlainAgent())
    assert [e.type for e in await _collect(client)] == [
        EventType.RUN_STARTED,
        EventType.RUN_FINISHED,
    ]
    assert repr(client) == "InProcessAGUIClient(agent=_PlainAgent)"
