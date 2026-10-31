"""``RunInputBuilder``: ConversationState -> ``RunAgentInput`` (T-016, DM §7.3, API §8.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from ag_ui.core import (
    AssistantMessage,
    DeveloperMessage,
    FunctionCall,
    MessagesSnapshotEvent,
    ReasoningMessage,
    ResumeEntry,
    RunAgentInput,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from ag_ui.core import ToolCall as AguiToolCall
from helpers.fixtures import discover_fixtures, fixture_ids, load_fixture, replay

from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import (
    ChatMessage,
    InterruptAnswer,
    MessageRole,
    ReasoningRecord,
    ReducerConfig,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from reflex_agentkit.core.reducer import reduce
from reflex_agentkit.core.run_input import RunInputBuilder, to_agui_messages
from reflex_agentkit.core.tools import client_tool

CONFIG = ReducerConfig()


@client_tool
def pick_date(day: int) -> str:
    """Pick a date."""
    return str(day)


def _conv(**changes: object) -> ConversationState:
    conv = begin_run(ConversationState.initial(CONFIG), config=CONFIG, new_id=iter("tr").__next__)
    return conv.with_(**changes)


def test_REQ_001_2_input_carries_thread_run_and_protocol_version() -> None:
    """REQ-001.2, API §8.1: IDs, ``protocolVersion`` 1.0, empty context and props."""
    run_input = RunInputBuilder().build(_conv())
    assert (run_input.thread_id, run_input.run_id) == ("t", "r")
    assert run_input.protocol_version == "1.0"
    assert (run_input.context, run_input.forwarded_props, run_input.resume) == ([], {}, None)
    assert run_input.tools == []


def test_REQ_016_7_shared_state_is_sent() -> None:
    """REQ-016.7: the shared state goes out as ``state``."""
    run_input = RunInputBuilder().build(_conv(shared_state={"items": [1]}))
    assert run_input.state == {"items": [1]}


def test_REQ_018_1_client_tools_are_advertised() -> None:
    """REQ-018.1: every registered client tool is in ``tools``."""
    run_input = RunInputBuilder(client_tools=(pick_date,)).build(_conv())
    assert run_input.tools == [pick_date.to_agui_tool()]


def test_REQ_013_5_resume_entries_are_sent_when_present() -> None:
    """REQ-013.5, API §7.4: ``resume`` carries the captured answers."""
    conv = _conv(
        resume=(
            InterruptAnswer(interrupt_id="i1", status="resolved", payload={"approved": True}),
            InterruptAnswer(interrupt_id="i2", status="cancelled"),
        )
    )
    assert RunInputBuilder().build(conv).resume == [
        ResumeEntry(interrupt_id="i1", status="resolved", payload={"approved": True}),
        ResumeEntry(interrupt_id="i2", status="cancelled"),
    ]


def test_REQ_001_2_messages_are_converted_by_role() -> None:
    """DM §7.3: user/system/developer/assistant (with calls)/tool messages."""
    conv = _conv(
        messages=(
            ChatMessage(id="s", role=MessageRole.SYSTEM, content="be brief"),
            ChatMessage(id="d", role=MessageRole.DEVELOPER, content="dev note"),
            ChatMessage(id="u", role=MessageRole.USER, content="hi"),
            ChatMessage(id="a", role=MessageRole.ASSISTANT, tool_call_ids=("c1", "c2")),
            ChatMessage(id="t1", role=MessageRole.TOOL, content="ok", tool_call_id="c1"),
            ChatMessage(
                id="t2", role=MessageRole.TOOL, content="boom", tool_call_id="c2", is_error=True
            ),
            ChatMessage(id="a2", role=MessageRole.ASSISTANT, content="done"),
        ),
        tool_calls=(
            ToolCall(
                id="c1",
                name="edit",
                args={"city": "Porto"},
                args_text='{"city": "Lisbon"}',
                status=ToolCallStatus.DONE,
                parent_message_id="a",
            ),
            ToolCall(id="c2", name="bad", status=ToolCallStatus.ERROR, parent_message_id="a"),
        ),
    )
    assert to_agui_messages(conv) == [
        SystemMessage(id="s", content="be brief"),
        DeveloperMessage(id="d", content="dev note"),
        UserMessage(id="u", content="hi"),
        AssistantMessage(
            id="a",
            content=None,
            tool_calls=[
                AguiToolCall(
                    id="c1", function=FunctionCall(name="edit", arguments='{"city": "Porto"}')
                ),
                AguiToolCall(id="c2", function=FunctionCall(name="bad", arguments="{}")),
            ],
        ),
        ToolMessage(id="t1", content="ok", tool_call_id="c1"),
        ToolMessage(id="t2", content="boom", tool_call_id="c2", error="boom"),
        AssistantMessage(id="a2", content="done"),
    ]


def test_REQ_011_2_encrypted_reasoning_resent() -> None:
    """REQ-011.2: reasoning goes back with its encrypted value, before its assistant message."""
    conv = _conv(
        messages=(
            ChatMessage(id="u", role=MessageRole.USER, content="think"),
            ChatMessage(id="a", role=MessageRole.ASSISTANT, content="42"),
        ),
        reasoning=(
            ReasoningRecord(
                id="r1", assistant_message_id="a", content="hmm", encrypted_value="ENC"
            ),
            ReasoningRecord(id="r2", assistant_message_id="a"),
            ReasoningRecord(id="r3", content="loose"),
        ),
    )
    assert to_agui_messages(conv) == [
        UserMessage(id="u", content="think"),
        ReasoningMessage(id="r1", content="hmm", encrypted_value="ENC"),
        AssistantMessage(id="a", content="42"),
        ReasoningMessage(id="r3", content="loose"),
    ]


FIXTURES = discover_fixtures()


@pytest.mark.parametrize("path", FIXTURES, ids=fixture_ids(FIXTURES))
def test_REQ_001_2_egress_validates_and_round_trips(path: Path) -> None:
    """DM §7.3: the input validates, and ingress(snapshot(egress(conv))) == conv.messages."""
    conv = replay(load_fixture(path)).conv
    run_input = RunInputBuilder().build(conv)
    RunAgentInput.model_validate(run_input.model_dump(mode="json", by_alias=True))

    snapshot = MessagesSnapshotEvent(messages=run_input.messages)
    again = reduce(conv.with_(run_status=RunStatus.RUNNING), snapshot)

    def shape(c: ConversationState) -> list[tuple[object, ...]]:
        return [
            (m.id, m.role, m.content, m.tool_call_ids, m.tool_call_id, m.is_error)
            for m in c.messages
        ]

    assert shape(again) == shape(conv)
    assert again.diagnostics == ()
