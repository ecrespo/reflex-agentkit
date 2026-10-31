"""``ConversationState`` aggregate and its invariants (DM §3.10, §4, §8)."""

from __future__ import annotations

import dataclasses
import pickle
from collections.abc import Callable
from typing import Any

import pytest
from helpers.invariants import check_invariants, find_violations

from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    CustomEventRecord,
    InterruptAnswer,
    MessageRole,
    OpenInterrupt,
    ReasoningRecord,
    ReducerConfig,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)

CONFIG = ReducerConfig(custom_events_limit=2)


def _conv(**changes: Any) -> ConversationState:
    return ConversationState.initial(CONFIG).with_(**changes)


def _assistant(mid: str = "m1", calls: tuple[str, ...] = ()) -> ChatMessage:
    return ChatMessage(id=mid, role=MessageRole.ASSISTANT, content="x", tool_call_ids=calls)


# --- construction ------------------------------------------------------------------------


def test_DM_3_10_initial_state_has_the_documented_defaults() -> None:
    """DM §3.10: ``initial(config)`` yields an idle, empty conversation."""
    conv = ConversationState.initial(CONFIG)
    assert conv.schema_version == 1
    assert conv.thread_id == ""
    assert conv.run_id == ""
    assert conv.run_status is RunStatus.IDLE
    assert conv.error == ""
    assert conv.error_code is None
    assert conv.current_step == ""
    assert conv.messages == ()
    assert conv.tool_calls == ()
    assert conv.reasoning == ()
    assert conv.shared_state == {}
    assert conv.shared_state_stale is False
    assert conv.interrupts == ()
    assert conv.answers == {}
    assert conv.abandoned_interrupt_ids == ()
    assert conv.custom_events == ()
    assert conv.client_tool_rounds == 0
    assert conv.last_run_ids == ()
    assert conv.diagnostics == ()
    assert conv.dirty_tool_args == frozenset()
    assert conv.config is CONFIG
    check_invariants(conv)


def test_DM_3_10_conversation_is_frozen() -> None:
    """DM R-1: the aggregate is immutable."""
    conv = ConversationState.initial(CONFIG)
    with pytest.raises(dataclasses.FrozenInstanceError):
        conv.run_id = "r"  # type: ignore[misc]


def test_INV_2_indexes_follow_with_() -> None:
    """INV-2: ``with_`` rebuilds ``_tool_index``/``_message_index`` from the tuples."""
    conv = _conv(
        messages=(_assistant("m1", ("c1", "c2")), _assistant("m2")),
        tool_calls=(ToolCall(id="c1", name="a"), ToolCall(id="c2", name="b")),
        run_status=RunStatus.RUNNING,
    )
    assert conv._message_index == {"m1": 0, "m2": 1}
    assert conv._tool_index == {"c1": 0, "c2": 1}
    moved = conv.with_(tool_calls=conv.tool_calls[::-1], messages=conv.messages[1:])
    assert moved._tool_index == {"c2": 0, "c1": 1}
    assert moved._message_index == {"m2": 0}
    assert conv._tool_index == {"c1": 0, "c2": 1}, "the original is untouched"


def test_INV_2_indexes_are_excluded_from_equality() -> None:
    """DM §3.10: the derived indexes do not take part in ``==``."""
    conv = _conv(tool_calls=(ToolCall(id="c1", name="a", status=ToolCallStatus.DONE),))
    twin = _conv(tool_calls=(ToolCall(id="c1", name="a", status=ToolCallStatus.DONE),))
    object.__setattr__(twin, "_tool_index", {})
    assert conv == twin


def test_DM_3_10_with_returns_a_new_state() -> None:
    """DM R-2: ``with_`` never mutates the receiver."""
    conv = ConversationState.initial(CONFIG)
    changed = conv.with_(run_id="r1")
    assert changed.run_id == "r1"
    assert conv.run_id == ""


# --- pickling ----------------------------------------------------------------------------


def _rich_conv() -> ConversationState:
    return _conv(
        thread_id="t1",
        run_id="r1",
        messages=(_assistant("m1", ("c1",)),),
        tool_calls=(ToolCall(id="c1", name="a", status=ToolCallStatus.DONE),),
        shared_state={"count": 1},
        custom_events=(CustomEventRecord(name="n", value=1, run_id="r1"),),
    )


def test_DM_8_conversation_pickle_round_trips_and_rebuilds_indexes() -> None:
    """DM §8: the state manager's pickle round-trips, and indexes are rebuilt."""
    conv = _rich_conv()
    clone = pickle.loads(pickle.dumps(conv))  # noqa: S301  # round-trip of our own object
    assert clone == conv
    assert clone._tool_index == {"c1": 0}
    assert clone._message_index == {"m1": 0}
    check_invariants(clone)


def test_DM_8_conversation_pickle_excludes_the_derived_indexes() -> None:
    """DM §3.10: the derived indexes are not part of the pickled state."""
    state = _rich_conv()._to_state()
    assert "_tool_index" not in state
    assert "_message_index" not in state
    assert state["schema_version"] == 1


def test_DM_8_conversation_restores_from_a_tolerant_payload() -> None:
    """DM §8: a v1 payload missing a field and carrying an unknown one still loads."""
    state = _rich_conv()._to_state()
    del state["current_step"]
    state["field_from_the_future"] = {"x": 1}
    restored = ConversationState._from_state(state)
    assert restored.current_step == ""
    assert restored.messages == _rich_conv().messages
    assert restored._message_index == {"m1": 0}


def test_DM_8_restore_stamps_the_current_schema_version() -> None:
    """DM §8: upgrade steps run on restore, and the result carries the current version."""
    state = _rich_conv()._to_state()
    state.pop("schema_version")
    assert ConversationState._from_state(state).schema_version == 1


# --- invariant checker: one positive and one negative case per invariant ------------------


def test_invariants_hold_on_a_consistent_rich_state() -> None:
    """DM §4: a well-formed state passes every invariant."""
    conv = _conv(
        run_status=RunStatus.AWAITING_INPUT,
        messages=(
            _assistant("m1", ("c1",)),
            ChatMessage(id="t1", role=MessageRole.TOOL, tool_call_id="c1", content="ok"),
        ),
        tool_calls=(
            ToolCall(
                id="c1", name="a", status=ToolCallStatus.PENDING_APPROVAL, interrupt_id="int-c1"
            ),
        ),
        interrupts=(OpenInterrupt(id="int-c1", reason="tool_call", tool_call_id="c1"),),
        reasoning=(ReasoningRecord(id="r1", assistant_message_id="m1", encrypted_value="s3cr3t"),),
    )
    check_invariants(conv)


def _corrupt_index(conv: ConversationState) -> ConversationState:
    object.__setattr__(conv, "_tool_index", {"c1": 5})
    return conv


VIOLATIONS: dict[str, Callable[[], ConversationState]] = {
    "INV-1": lambda: _conv(messages=(_assistant("m1"), _assistant("m1"))),
    "INV-2": lambda: _corrupt_index(
        _conv(tool_calls=(ToolCall(id="c1", name="a", status=ToolCallStatus.DONE),))
    ),
    "INV-3": lambda: _conv(
        messages=(ChatMessage(id="t1", role=MessageRole.TOOL, tool_call_id="nope"),)
    ),
    "INV-4": lambda: _conv(run_status=RunStatus.AWAITING_INPUT),
    "INV-5": lambda: _conv(
        messages=(ChatMessage(id="m1", role=MessageRole.ASSISTANT, streaming=True),)
    ),
    "INV-6": lambda: _conv(
        run_status=RunStatus.RUNNING,
        tool_calls=(ToolCall(id="c1", name="a", status=ToolCallStatus.PENDING_APPROVAL),),
    ),
    "INV-7": lambda: _conv(
        answers={"ghost": InterruptAnswer(interrupt_id="ghost", status="resolved")}
    ),
    "INV-8": lambda: _conv(error_code=ErrorCode.AGENT_RUN_ERROR, error="boom"),
    "INV-9": lambda: _conv(
        custom_events=tuple(CustomEventRecord(name="n", value=i, run_id="r") for i in range(3))
    ),
    "INV-10": lambda: _conv(shared_state={"when": object()}),
    "INV-11": lambda: _conv(
        messages=(ChatMessage(id="m1", role=MessageRole.ASSISTANT, reasoning="s3cr3t"),),
        reasoning=(ReasoningRecord(id="r1", assistant_message_id="m1", encrypted_value="s3cr3t"),),
    ),
}


CHECKED_INVARIANTS = [f"INV-{n}" for n in range(1, 12)]


def test_INV_every_checked_invariant_has_a_negative_case() -> None:
    """DM §4: INV-1…INV-11 each have a hand-built violation below."""
    assert set(VIOLATIONS) == set(CHECKED_INVARIANTS)


@pytest.mark.parametrize("inv", CHECKED_INVARIANTS)
def test_INV_checker_flags_each_hand_built_violation(inv: str) -> None:
    """DM §4: ``check_invariants`` flags a hand-built violation of each invariant."""
    conv = VIOLATIONS[inv]()
    assert inv in find_violations(conv)
    with pytest.raises(AssertionError, match=inv):
        check_invariants(conv)


def test_INV_8_non_fatal_codes_may_coexist_with_any_status() -> None:
    """INV-8 (A-07): non-fatal codes do not force the error status."""
    check_invariants(_conv(error_code=ErrorCode.MESSAGE_TOO_LONG))
