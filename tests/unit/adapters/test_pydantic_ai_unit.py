"""``PydanticAIAgent`` (T-033, API §7.5, TD DD-011, REQ-022.1, REQ-022.4)."""

from __future__ import annotations

from typing import Any

import pytest
from ag_ui.core import BaseEvent, EventType, RunAgentInput, RunFinishedEvent, UserMessage
from pydantic_ai import Agent, DeferredToolRequests, RunContext
from pydantic_ai.models.test import TestModel

from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent
from reflex_agentkit.core.clients.base import AGUIAgent
from reflex_agentkit.core.errors import ConfigurationError


def _input(text: str = "hi") -> RunAgentInput:
    return RunAgentInput(
        thread_id="t",
        run_id="r1",
        messages=[UserMessage(id="u1", content=text)],
        tools=[],
        context=[],
        state={},
        forwarded_props={},
    )


async def _events(
    agent: PydanticAIAgent, run_input: RunAgentInput | None = None
) -> list[BaseEvent]:
    return [e async for e in agent.run(run_input or _input())]


def _outcome(events: list[BaseEvent]) -> str:
    last = events[-1]
    assert isinstance(last, RunFinishedEvent)
    return str(getattr(last.outcome, "type", "success"))


async def test_REQ_022_1_text_reply_streams_from_run_started_to_run_finished() -> None:
    """REQ-022.1: the adapter drives ``AGUIAdapter`` in process and yields AG-UI events."""
    adapter = PydanticAIAgent(Agent(TestModel(custom_output_text="hello"), output_type=str))
    assert isinstance(adapter, AGUIAgent)
    events = await _events(adapter)
    assert events[0].type is EventType.RUN_STARTED
    assert events[-1].type is EventType.RUN_FINISHED
    text = "".join(
        getattr(e, "delta", "") for e in events if e.type is EventType.TEXT_MESSAGE_CONTENT
    )
    assert text == "hello"
    assert _outcome(events) == "success"


async def test_REQ_022_4_injects_deferred_requests() -> None:
    """REQ-022.4, DD-011: a plain ``str`` agent with an approval tool pauses on an interrupt."""
    agent = Agent(TestModel(call_tools=["book_hotel"]), output_type=str)

    @agent.tool_plain(requires_approval=True)
    def book_hotel(city: str) -> str:
        return f"booked {city}"

    events = await _events(PydanticAIAgent(agent))
    assert _outcome(events) == "interrupt"
    last = events[-1]
    assert isinstance(last, RunFinishedEvent)
    interrupt = last.outcome.interrupts[0]  # type: ignore[union-attr]
    assert (interrupt.reason, interrupt.tool_call_id) == (
        "tool_call",
        "pyd_ai_tool_call_id__book_hotel",
    )


async def test_REQ_022_4_declared_deferred_requests_are_not_added_twice() -> None:
    """DD-011: an agent that already declares ``DeferredToolRequests`` works unchanged."""
    agent = Agent(TestModel(call_tools=["book_hotel"]), output_type=[str, DeferredToolRequests])

    @agent.tool_plain(requires_approval=True)
    def book_hotel(city: str) -> str:
        return f"booked {city}"

    assert _outcome(await _events(PydanticAIAgent(agent))) == "interrupt"


async def test_API_7_5_deps_reach_the_tools() -> None:
    """API §7.5: ``deps`` is passed to ``run_stream``."""
    seen: list[Any] = []
    agent = Agent(TestModel(call_tools=["whoami"]), output_type=str, deps_type=str)

    @agent.tool
    def whoami(ctx: RunContext[str]) -> str:
        seen.append(ctx.deps)
        return ctx.deps

    await _events(PydanticAIAgent(agent, deps="alice"))
    assert seen == ["alice"]


@pytest.mark.parametrize("is_async", [False, True])
async def test_API_7_5_deps_factory_receives_the_run_input(is_async: bool) -> None:
    """API §7.5: the factory (sync or async) builds per-run deps from the input."""
    seen: list[Any] = []
    agent = Agent(TestModel(call_tools=["whoami"]), output_type=str, deps_type=str)

    @agent.tool
    def whoami(ctx: RunContext[str]) -> str:
        seen.append(ctx.deps)
        return ctx.deps

    def sync_factory(run_input: RunAgentInput) -> str:
        return f"thread {run_input.thread_id}"

    async def async_factory(run_input: RunAgentInput) -> str:
        return f"thread {run_input.thread_id}"

    await _events(PydanticAIAgent(agent, deps_factory=async_factory if is_async else sync_factory))
    assert seen == ["thread t"]


async def test_API_7_5_run_kwargs_are_forwarded() -> None:
    """API §7.5: extra keyword arguments go to ``run_stream``."""
    agent = Agent(TestModel(custom_output_text="default"), output_type=str)
    events = await _events(PydanticAIAgent(agent, model=TestModel(custom_output_text="override")))
    text = "".join(
        getattr(e, "delta", "") for e in events if e.type is EventType.TEXT_MESSAGE_CONTENT
    )
    assert text == "override"


def test_API_7_5_deps_and_deps_factory_are_exclusive() -> None:
    """API §7.5: setting both is a ``ConfigurationError``."""
    agent = Agent(TestModel(), output_type=str)
    with pytest.raises(ConfigurationError, match="deps"):
        PydanticAIAgent(agent, deps=1, deps_factory=lambda run_input: 2)


def test_API_7_5_requires_a_pydantic_ai_agent() -> None:
    """API §7.5: anything else is a ``ConfigurationError``."""
    with pytest.raises(ConfigurationError, match="pydantic_ai"):
        PydanticAIAgent(object())  # type: ignore[arg-type]


def test_API_7_5_repr_does_not_leak_deps() -> None:
    """REQ-025: deps may hold secrets; the repr names only the agent."""
    agent = Agent(TestModel(), output_type=str, name="helper")
    assert "SECRET" not in repr(PydanticAIAgent(agent, deps="SECRET"))
