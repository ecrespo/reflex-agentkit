"""Value types, enums and tolerant pickling (DM §2, §3, §6, §8; API §5)."""

from __future__ import annotations

import dataclasses
import json
import pickle
from typing import Any

import pytest

from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    CustomEventRecord,
    Diagnostic,
    DiagnosticCode,
    InterruptAnswer,
    MessageRole,
    OpenInterrupt,
    PendingInterrupt,
    ReasoningRecord,
    ReducerConfig,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)

SAMPLES: list[Any] = [
    ChatMessage(id="m1", role=MessageRole.ASSISTANT, content="hi", tool_call_ids=("c1",)),
    ToolCall(id="c1", name="get_weather", args_text='{"city": "Lisbon"}', args={"city": "Lisbon"}),
    PendingInterrupt(
        id="i1",
        reason="human_input",
        message="Pick one",
        payload={"options": [1, 2]},
        response_schema=None,
        queue_position=1,
        queue_size=2,
    ),
    OpenInterrupt(id="int-c1", reason="tool_call", tool_call_id="c1"),
    InterruptAnswer(interrupt_id="int-c1", status="resolved", payload={"approved": True}),
    ReasoningRecord(id="r1", assistant_message_id="m1", content="thinking"),
    CustomEventRecord(name="progress", value={"pct": 50}, run_id="run-1"),
    Diagnostic(level="warning", code=DiagnosticCode.UNKNOWN_EVENT_TYPE, message="?"),
    ReducerConfig(client_tool_names=frozenset({"pick_date"})),
]


def _ids(value: Any) -> str:
    return type(value).__name__


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (MessageRole, {"user", "assistant", "tool", "system", "developer"}),
        (RunStatus, {"idle", "running", "awaiting_input", "cancelled", "error"}),
        (
            ToolCallStatus,
            {"streaming", "pending_approval", "running", "done", "rejected", "error"},
        ),
        (
            DiagnosticCode,
            {
                "UNKNOWN_EVENT_TYPE",
                "INVALID_EVENT",
                "IMPLICIT_MESSAGE",
                "UNKNOWN_MESSAGE_ID",
                "UNKNOWN_TOOL_CALL_ID",
                "DUPLICATE_ID",
                "STALE_RUN_EVENT",
                "PATCH_FAILED",
                "ARGS_TOO_LARGE",
                "IGNORED_EVENT",
            },
        ),
    ],
)
def test_DM_6_enums_have_the_normative_values(enum: Any, values: set[str]) -> None:
    """DM §6: every enum has exactly the listed values."""
    assert {member.value for member in enum} == values


def test_DM_2_R3_str_enums_compare_equal_to_strings() -> None:
    """DM R-3, API §5.5: ``run_status == "running"`` and ``== RunStatus.RUNNING`` both hold."""
    running: str = RunStatus.RUNNING
    pending: str = ToolCallStatus.PENDING_APPROVAL
    assert running == "running"
    assert pending == "pending_approval"
    assert RunStatus("running") is RunStatus.RUNNING


PUBLIC_SAMPLES = [v for v in SAMPLES if not isinstance(v, ReducerConfig)]


@pytest.mark.parametrize("value", PUBLIC_SAMPLES, ids=_ids)
def test_DM_2_R3_values_serialize_enums_as_plain_strings(value: Any) -> None:
    """DM R-3: ``json.dumps(asdict(...))`` writes enum values, not ``Enum.X`` reprs.

    ``ReducerConfig`` is excluded: it is internal and holds a ``frozenset``.
    """
    text = json.dumps(dataclasses.asdict(value))
    assert "MessageRole." not in text
    assert "ToolCallStatus." not in text
    assert "DiagnosticCode." not in text


def test_DM_2_R3_tool_call_status_serializes_to_its_value() -> None:
    """DM R-3: a tool call's status goes to the browser as ``"done"``."""
    call = ToolCall(id="c1", name="t", status=ToolCallStatus.DONE)
    assert json.loads(json.dumps(dataclasses.asdict(call)))["status"] == "done"


@pytest.mark.parametrize("value", SAMPLES, ids=_ids)
def test_DM_2_R1_values_are_frozen_and_slotted(value: Any) -> None:
    """DM R-1: every value type is a frozen, slotted dataclass."""
    field = dataclasses.fields(value)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(value, field, None)
    assert not hasattr(value, "__dict__")


def test_DM_3_1_chat_message_defaults() -> None:
    """DM §3.1: defaults of ``ChatMessage``."""
    msg = ChatMessage(id="m1", role=MessageRole.USER)
    assert msg.content == ""
    assert msg.streaming is False
    assert msg.tool_call_ids == ()
    assert msg.tool_call_id is None
    assert msg.reasoning == ""
    assert msg.is_error is False


def test_DM_3_2_tool_call_defaults() -> None:
    """DM §3.2: defaults of ``ToolCall``."""
    call = ToolCall(id="c1", name="t")
    assert call.args_text == ""
    assert call.args is None
    assert call.status is ToolCallStatus.STREAMING
    assert call.result is None
    assert call.parent_message_id is None
    assert call.interrupt_id is None
    assert call.is_client_tool is False


def test_DM_3_4_open_interrupt_defaults() -> None:
    """DM §3.4: ``message`` defaults to ``""`` and the interrupt is not local."""
    interrupt = OpenInterrupt(id="i1", reason="human_input")
    assert interrupt.message == ""
    assert interrupt.tool_call_id is None
    assert interrupt.payload is None
    assert interrupt.response_schema is None
    assert interrupt.is_local is False


def test_DM_3_9_reducer_config_defaults() -> None:
    """DM §3.9, API §4.1: args cap of 1 MiB and a 100-entry custom-event ring."""
    config = ReducerConfig()
    assert config.client_tool_names == frozenset()
    assert config.custom_events_limit == 100
    assert config.max_args_bytes == 1_048_576


def test_DM_3_8_diagnostic_event_type_defaults_to_none() -> None:
    """DM §3.8: ``Diagnostic.event_type`` is optional."""
    diag = Diagnostic(level="debug", code=DiagnosticCode.IGNORED_EVENT, message="raw")
    assert diag.event_type is None


@pytest.mark.parametrize("value", SAMPLES, ids=_ids)
def test_DM_8_values_pickle_round_trip(value: Any) -> None:
    """DM §8: every value type survives the state manager's pickle."""
    clone = pickle.loads(pickle.dumps(value))  # noqa: S301  # round-trip of our own object
    assert clone == value
    assert type(clone) is type(value)


def test_DM_8_pickle_payload_carries_the_schema_version() -> None:
    """DM §8: the pickled state is ``{"schema_version": n, **fields}``."""
    state = ChatMessage(id="m1", role=MessageRole.USER)._to_state()
    assert state["schema_version"] == 1
    assert state["id"] == "m1"


def test_DM_8_restore_fills_a_missing_field_with_its_default() -> None:
    """DM §8: a pickle from an older version that lacks a field still loads."""
    state = ChatMessage(id="m1", role=MessageRole.USER, content="hi")._to_state()
    del state["is_error"]
    restored = ChatMessage._from_state(state)
    assert restored == ChatMessage(id="m1", role=MessageRole.USER, content="hi")


def test_DM_8_restore_drops_an_unknown_field() -> None:
    """DM §8: a pickle from a newer version with an extra field still loads."""
    state = ToolCall(id="c1", name="t")._to_state()
    state["field_from_the_future"] = 42
    assert ToolCall._from_state(state) == ToolCall(id="c1", name="t")


def test_DM_8_restore_rejects_a_missing_required_field() -> None:
    """DM §8: a required field with no default cannot be invented."""
    state = ToolCall(id="c1", name="t")._to_state()
    del state["name"]
    with pytest.raises(TypeError, match="name"):
        ToolCall._from_state(state)


def test_DM_8_pickle_goes_through_the_tolerant_restore() -> None:
    """DM §8 v1.2: ``__reduce__`` (not the dataclass ``__setstate__``) drives unpickling."""
    func, args = ChatMessage(id="m1", role=MessageRole.USER).__reduce__()
    restored = func(*args)
    assert restored == ChatMessage(id="m1", role=MessageRole.USER)


def test_DM_3_error_code_is_importable_next_to_models() -> None:
    """DM §3.10: ``ErrorCode`` is the type of ``ConversationState.error_code``."""
    assert ErrorCode("AGENT_RUN_ERROR") is ErrorCode.AGENT_RUN_ERROR
