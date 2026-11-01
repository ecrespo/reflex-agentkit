"""PydanticAI end to end through ``AgentState`` (T-034, REQ-022.2-3, REQ-013.5, REQ-018.2).

``PydanticAIAgent`` → ``InProcessAGUIClient`` → driver and reducer → commands →
``RunInputBuilder`` → back to PydanticAI on resume. ``TestModel`` keeps it offline.
"""

from __future__ import annotations

import logging
from typing import ClassVar

import pytest
import reflex as rx
from helpers.reflex_harness import ReflexHarness
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from reflex_agentkit import AgentState, client_tool
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent
from reflex_agentkit.core.models import RunStatus, ToolCallStatus

booked: list[str] = []


def _hotel_agent() -> Agent[None, str]:
    agent = Agent(TestModel(call_tools=["book_hotel"]), output_type=str)

    @agent.tool_plain(requires_approval=True)
    def book_hotel(city: str) -> str:
        """Book a hotel."""
        booked.append(city)
        return f"booked {city}"

    return agent


class HotelState(AgentState, rx.State):
    agent: ClassVar = PydanticAIAgent(_hotel_agent())


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    booked.clear()


async def _pause(rx_: ReflexHarness, token: str) -> HotelState:
    await rx_.call(token, HotelState, "send_message", text="book a hotel")
    state = await rx_.state(token, HotelState)
    assert state.run_status == RunStatus.AWAITING_INPUT
    assert [c.name for c in state.pending_approvals] == ["book_hotel"]
    assert booked == []
    return state


async def test_REQ_022_2_approve_runs_the_tool(reflex_harness: ReflexHarness) -> None:
    """REQ-022.2, REQ-013.5: approval resumes the agent and the tool runs."""
    state = await _pause(reflex_harness, "approve")
    call_id = state.pending_approvals[0].id
    await reflex_harness.call("approve", HotelState, "approve_tool", call_id=call_id)
    state = await reflex_harness.state("approve", HotelState)
    assert state.run_status == RunStatus.IDLE
    assert booked == ["a"]  # TestModel's generated argument
    call = state.tool_calls[0]
    assert (call.status, call.result) == (ToolCallStatus.DONE, "booked a")  # REQ-035.3
    assert state.messages[-1].role == "assistant"


NOTICE = (
    "booked Porto\n\nNote: the user edited this tool call's arguments before approving it. "
    'The tool ran with: {"city": "Porto"}.'
)


async def test_REQ_022_3_approve_with_edited_args(reflex_harness: ReflexHarness) -> None:
    """REQ-022.3, REQ-035.1: the tool gets the edits and the model is told about them."""
    state = await _pause(reflex_harness, "edit")
    call_id = state.pending_approvals[0].id
    await reflex_harness.call(
        "edit", HotelState, "approve_tool", call_id=call_id, edited_args={"city": "Porto"}
    )
    state = await reflex_harness.state("edit", HotelState)
    assert booked == ["Porto"]
    assert state.tool_calls[0].result == NOTICE
    assert state.run_status == RunStatus.IDLE


class QuietHotelState(AgentState, rx.State):
    agent: ClassVar = PydanticAIAgent(_hotel_agent(), notify_edited_args=False)


async def test_REQ_035_4_notice_can_be_turned_off(reflex_harness: ReflexHarness) -> None:
    """REQ-035.4: ``notify_edited_args=False`` leaves the tool result as the tool returned it."""
    await reflex_harness.call("quiet", QuietHotelState, "send_message", text="book a hotel")
    state = await reflex_harness.state("quiet", QuietHotelState)
    call_id = state.pending_approvals[0].id
    await reflex_harness.call(
        "quiet", QuietHotelState, "approve_tool", call_id=call_id, edited_args={"city": "Porto"}
    )
    state = await reflex_harness.state("quiet", QuietHotelState)
    assert booked == ["Porto"]
    assert state.tool_calls[0].result == "booked Porto"


async def test_REQ_035_6_notice_is_logged_only_at_debug(
    reflex_harness: ReflexHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-035.6: the notice holds user content, so nothing about it is logged above DEBUG."""
    caplog.set_level(logging.DEBUG, logger="reflex_agentkit")
    state = await _pause(reflex_harness, "log")
    await reflex_harness.call(
        "log",
        HotelState,
        "approve_tool",
        call_id=state.pending_approvals[0].id,
        edited_args={"city": "Porto"},
    )
    porto = [r for r in caplog.records if "Porto" in r.getMessage()]
    assert porto, "the notice is logged at DEBUG"
    assert all(r.levelno == logging.DEBUG for r in porto)


async def test_REQ_022_2_reject_does_not_run_the_tool(reflex_harness: ReflexHarness) -> None:
    """REQ-022.2: rejection resumes without running the tool; the model sees the denial."""
    state = await _pause(reflex_harness, "reject")
    call_id = state.pending_approvals[0].id
    await reflex_harness.call(
        "reject", HotelState, "reject_tool", call_id=call_id, reason="too expensive"
    )
    state = await reflex_harness.state("reject", HotelState)
    assert booked == []
    assert state.run_status == RunStatus.IDLE
    assert state.tool_calls[0].status == ToolCallStatus.REJECTED
    assert "too expensive" in state.messages[-1].content


picked: list[int] = []


@client_tool
def pick_day(day: int) -> str:
    """Let the user pick a day of the month."""
    picked.append(day)
    return f"day {day}"


class PickState(AgentState, rx.State):
    agent: ClassVar = PydanticAIAgent(Agent(TestModel(call_tools=["pick_day"]), output_type=str))
    client_tools: ClassVar = (pick_day,)


async def test_REQ_018_2_client_tool_result_is_fed_back(reflex_harness: ReflexHarness) -> None:
    """REQ-018.2: PydanticAI calls the frontend tool; its result reaches the follow-up run."""
    picked.clear()
    await reflex_harness.call("pick", PickState, "send_message", text="pick a day")
    state = await reflex_harness.state("pick", PickState)
    assert picked == [0]
    call = state.tool_calls[0]
    assert (call.name, call.status, call.result) == ("pick_day", ToolCallStatus.DONE, "day 0")
    assert state.run_status == RunStatus.IDLE
    assert "day 0" in state.messages[-1].content
