"""``request_tool_approval`` and the native resume shapes (T-043, REQ-034.2-3, DD-012)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from ag_ui.core import Interrupt, ResumeEntry
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command

from reflex_agentkit.adapters import langgraph as adapter
from reflex_agentkit.adapters.langgraph import (
    ApprovalDecision,
    LangGraphAGUIAgent,
    request_tool_approval,
)

ARGS = {"city": "Lisbon", "nights": 2}


def _agent() -> LangGraphAGUIAgent:
    builder = StateGraph(MessagesState)
    builder.add_node("noop", lambda state: {})
    builder.add_edge(START, "noop")
    builder.add_edge("noop", END)
    return LangGraphAGUIAgent(builder.compile(checkpointer=InMemorySaver()))


def _entry(interrupt_id: str, payload: Any = None, *, cancelled: bool = False) -> ResumeEntry:
    if cancelled:
        return ResumeEntry(interrupt_id=interrupt_id, status="cancelled")
    return ResumeEntry(interrupt_id=interrupt_id, status="resolved", payload=payload)


OPEN = [
    Interrupt(id="i-tool", reason="tool_call", tool_call_id="c1"),
    Interrupt(id="i-ask", reason="confirm", message="Proceed?"),
]


def _command(entries: list[ResumeEntry]) -> Command[Any]:
    return _agent()._build_command_from_agui_resume(entries, open_interrupts=OPEN)


def test_DD_012_single_resolved_entry_resumes_with_its_payload() -> None:
    """REQ-034.2: ``Command(resume=payload)``."""
    assert _command([_entry("i-ask", {"ok": True})]).resume == {"ok": True}


def test_DD_012_multiple_entries_use_the_native_resume_map() -> None:
    """DD-012: each interrupted node receives its own answer."""
    command = _command([_entry("i-tool", {"approved": True}), _entry("i-ask", "yes")])
    assert command.resume == {"i-tool": {"approved": True}, "i-ask": "yes"}


def test_DD_012_cancelled_tool_approval_becomes_a_rejection() -> None:
    """API §7.6: a cancelled approval resolves to ``approved=False, reason="cancelled"``."""
    assert _command([_entry("i-tool", cancelled=True)]).resume == {
        "approved": False,
        "reason": "cancelled",
    }


def test_DD_012_cancelled_generic_interrupt_keeps_the_upstream_sentinel() -> None:
    """API §7.6: graph authors check ``__agui_cancelled__``."""
    assert _command([_entry("i-ask", cancelled=True)]).resume == {
        "__agui_cancelled__": True,
        "interrupt_id": "i-ask",
    }
    mixed = _command([_entry("i-tool", cancelled=True), _entry("i-ask", cancelled=True)])
    assert mixed.resume == {
        "i-tool": {"approved": False, "reason": "cancelled"},
        "i-ask": {"__agui_cancelled__": True, "interrupt_id": "i-ask"},
    }


@dataclasses.dataclass
class FakeInterrupt:
    """Stands in for LangGraph's ``interrupt``: records the value, returns ``reply``."""

    reply: Any = None
    values: list[Any] = dataclasses.field(default_factory=list)

    def __call__(self, value: Any) -> Any:
        self.values.append(value)
        return self.reply


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeInterrupt:
    recorder = FakeInterrupt()
    monkeypatch.setattr(adapter, "interrupt", recorder)
    return recorder


def _approve(fake: FakeInterrupt, payload: Any, **kwargs: Any) -> ApprovalDecision:
    fake.reply = payload
    return request_tool_approval("c1", "book_hotel", dict(ARGS), **kwargs)


def test_REQ_034_3_interrupt_value_uses_the_native_keys(fake: FakeInterrupt) -> None:
    """DD-012: the keys ag-ui-langgraph maps onto the AG-UI ``Interrupt``."""
    _approve(fake, {"approved": True}, message="Book it?")
    assert fake.values[0] == {
        "reason": "tool_call",
        "toolCallId": "c1",
        "toolName": "book_hotel",
        "args": ARGS,
        "message": "Book it?",
        "responseSchema": adapter.APPROVAL_RESPONSE_SCHEMA,
    }


def test_REQ_034_3_default_message_names_the_tool(fake: FakeInterrupt) -> None:
    _approve(fake, {"approved": True})
    assert fake.values[0]["message"] == "Approve book_hotel?"


def test_REQ_034_3_approved_returns_the_original_args(fake: FakeInterrupt) -> None:
    assert _approve(fake, {"approved": True}) == ApprovalDecision(approved=True, args=ARGS)


def test_REQ_034_3_edited_args_take_precedence(fake: FakeInterrupt) -> None:
    decision = _approve(fake, {"approved": True, "editedArgs": {"city": "Porto", "nights": 3}})
    assert decision == ApprovalDecision(
        approved=True, args={"city": "Porto", "nights": 3}, edited=True
    )


def test_REQ_035_2_tool_result_appends_the_notice_when_edited(fake: FakeInterrupt) -> None:
    """REQ-035.2: an edited approval's result carries the edited-arguments notice."""
    decision = _approve(fake, {"approved": True, "editedArgs": {"city": "Porto", "nights": 3}})
    assert decision.tool_result("Booked.") == (
        "Booked.\n\nNote: the user edited this tool call's arguments before approving it, "
        'so the tool ran with: {"city": "Porto", "nights": 3}. These are the arguments the '
        "user wants: do not call the tool again to restore the earlier ones, and do not "
        "report the change as an error."
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"approved": True},
        {"approved": True, "editedArgs": dict(ARGS)},
        {"approved": False, "reason": "no"},
    ],
    ids=["plain", "unchanged-edit", "rejected"],
)
def test_REQ_035_3_tool_result_is_unchanged_without_edits(
    fake: FakeInterrupt, payload: Any
) -> None:
    """REQ-035.3, REQ-035.5: no notice without a real edit, nor on rejection."""
    decision = _approve(fake, payload)
    assert decision.edited is False
    assert decision.tool_result("Booked.") == "Booked."
    assert decision.tool_result({"ok": 1}) == {"ok": 1}


def test_REQ_034_3_rejection_carries_the_reason(fake: FakeInterrupt) -> None:
    decision = _approve(fake, {"approved": False, "reason": "too pricey"})
    assert decision == ApprovalDecision(approved=False, args=ARGS, reason="too pricey")


def test_REQ_034_3_cancelled_approval(fake: FakeInterrupt) -> None:
    decision = _approve(fake, {"approved": False, "reason": "cancelled"})
    assert decision == ApprovalDecision(approved=False, args=ARGS, reason="cancelled")


@pytest.mark.parametrize(
    "payload",
    [None, "yes", {"approved": "true"}, {"__agui_cancelled__": True, "interrupt_id": "x"}],
)
def test_REQ_034_3_malformed_answers_are_rejections(fake: FakeInterrupt, payload: Any) -> None:
    """Anything that is not ``approved: true`` rejects; edited args must be an object."""
    decision = _approve(fake, payload)
    assert decision.approved is False
    assert decision.args == ARGS


def test_REQ_034_3_non_object_edited_args_are_ignored(fake: FakeInterrupt) -> None:
    decision = _approve(fake, {"approved": True, "editedArgs": [1, 2]})
    assert decision == ApprovalDecision(approved=True, args=ARGS)
