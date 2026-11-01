"""Contract tests: PydanticAI behavior the adapter relies on (TD §8.4 item 2, DD-011).

Pinned against pydantic-ai-slim 2.64 (DD-001). A failure after an upgrade means DD-011,
the approval payload contract (API §7.4) or the client-tool flow must be revisited.
"""

from __future__ import annotations

import pytest
from ag_ui.core import (
    AssistantMessage,
    BaseEvent,
    FunctionCall,
    Message,
    ResumeEntry,
    RunAgentInput,
    RunFinishedEvent,
    Tool,
    ToolCall,
    ToolCallArgsEvent,
    ToolCallStartEvent,
    UserMessage,
)
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.models.test import TestModel
from pydantic_ai.ui.ag_ui import AGUIAdapter


@pytest.fixture(autouse=True)
def _no_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")


def _input(
    run_id: str,
    messages: list[Message],
    *,
    tools: list[Tool] | None = None,
    resume: list[ResumeEntry] | None = None,
) -> RunAgentInput:
    return RunAgentInput(
        thread_id="t",
        run_id=run_id,
        messages=messages,
        tools=tools or [],
        context=[],
        state={},
        forwarded_props={},
        resume=resume,
    )


async def _run(agent: Agent[None, str], run_input: RunAgentInput) -> list[BaseEvent]:
    adapter = AGUIAdapter(agent=agent, run_input=run_input)
    stream = adapter.run_stream(output_type=[agent.output_type, DeferredToolRequests])
    return [e async for e in stream]


def _hotel(calls: list[str]) -> Agent[None, str]:
    agent = Agent(TestModel(call_tools=["book_hotel"]), output_type=str)

    @agent.tool_plain(requires_approval=True)
    def book_hotel(city: str) -> str:
        calls.append(city)
        return f"booked {city}"

    return agent


async def test_TD_8_4_2_approval_tool_pauses_with_the_interrupt_shape() -> None:
    """DD-011: injected ``DeferredToolRequests`` → interrupt ``int-<call_id>`` with the schema."""
    events = await _run(_hotel([]), _input("r1", [UserMessage(id="u1", content="book")]))
    last = events[-1]
    assert isinstance(last, RunFinishedEvent)
    assert last.outcome is not None
    assert last.outcome.type == "interrupt"
    (interrupt,) = last.outcome.interrupts
    start = next(e for e in events if isinstance(e, ToolCallStartEvent))
    assert interrupt.id == f"int-{start.tool_call_id}"
    assert (interrupt.reason, interrupt.tool_call_id) == ("tool_call", start.tool_call_id)
    assert interrupt.response_schema is not None
    assert set(interrupt.response_schema["properties"]) == {"approved", "editedArgs", "reason"}


async def test_TD_8_4_2_edited_args_override_on_resume() -> None:
    """API §7.4: ``{"approved": true, "editedArgs": …}`` runs the tool with the edits."""
    calls: list[str] = []
    agent = _hotel(calls)
    first = await _run(agent, _input("r1", [UserMessage(id="u1", content="book")]))
    start = next(e for e in first if isinstance(e, ToolCallStartEvent))
    args = "".join(e.delta for e in first if isinstance(e, ToolCallArgsEvent))
    history: list[Message] = [
        UserMessage(id="u1", content="book"),
        AssistantMessage(
            id=start.parent_message_id or "a1",
            tool_calls=[
                ToolCall(
                    id=start.tool_call_id,
                    type="function",
                    function=FunctionCall(name="book_hotel", arguments=args),
                )
            ],
        ),
    ]
    resume = [
        ResumeEntry(
            interrupt_id=f"int-{start.tool_call_id}",
            status="resolved",
            payload={"approved": True, "editedArgs": {"city": "Porto"}},
        )
    ]
    second = await _run(agent, _input("r2", history, resume=resume))
    assert calls == ["Porto"]
    last = second[-1]
    assert isinstance(last, RunFinishedEvent)
    assert last.outcome is None or last.outcome.type == "success"


async def test_TD_8_4_2_frontend_tool_call_ends_with_success_not_interrupt() -> None:
    """Analyze A-18: a client (frontend) tool call ends the run with ``outcome=success``."""
    agent = Agent(TestModel(call_tools=["pick_day"]), output_type=str)
    tool = Tool(
        name="pick_day",
        description="Pick a day.",
        parameters={"type": "object", "properties": {"day": {"type": "integer"}}},
    )
    events = await _run(agent, _input("r1", [UserMessage(id="u1", content="pick")], tools=[tool]))
    starts = [e for e in events if isinstance(e, ToolCallStartEvent)]
    assert [s.tool_call_name for s in starts] == ["pick_day"]
    last = events[-1]
    assert isinstance(last, RunFinishedEvent)
    assert last.outcome is None or last.outcome.type == "success"
    pending = getattr(last.outcome, "pending_tool_call_ids", None)
    assert pending in (None, [starts[0].tool_call_id])


def test_TD_DD_013_interrupt_ids_map_back_to_tool_call_ids() -> None:
    """DD-013: the private helper the adapter uses to find the edited call still exists."""
    from pydantic_ai.ui.ag_ui._interrupt import interrupt_id_to_tool_call_id

    assert interrupt_id_to_tool_call_id("int-call_1") == "call_1"


def test_TD_DD_013_run_stream_accepts_run_level_capabilities() -> None:
    """DD-013: the notice rides on a per-run capability, merged with the agent's own."""
    import inspect

    assert "capabilities" in inspect.signature(AGUIAdapter.run_stream).parameters
