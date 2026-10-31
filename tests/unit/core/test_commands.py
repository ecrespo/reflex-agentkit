"""Pure command functions (T-015; ``begin_run``'s basic part is pulled into T-010)."""

from __future__ import annotations

import uuid

from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import MessageRole, ReducerConfig, RunStatus

CONFIG = ReducerConfig(client_tool_names=frozenset({"pick"}))


def _is_uuid4(value: str) -> bool:
    return str(uuid.UUID(value, version=4)) == value


def test_REQ_001_1_begin_run_appends_the_user_message() -> None:
    """REQ-001.1: the human's turn is appended as a ``user`` message with a UUID4 ID."""
    conv = begin_run(ConversationState.initial(CONFIG), user_text="hello", config=CONFIG)
    assert len(conv.messages) == 1
    msg = conv.messages[0]
    assert msg.role is MessageRole.USER
    assert msg.content == "hello"
    assert _is_uuid4(msg.id)
    check_invariants(conv)


def test_REQ_001_2_begin_run_assigns_a_new_uuid4_run_id() -> None:
    """REQ-001.2: every run gets a fresh UUID4 ``run_id``."""
    first = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    second = begin_run(first.with_(run_status=RunStatus.IDLE), user_text="b", config=CONFIG)
    assert _is_uuid4(first.run_id)
    assert _is_uuid4(second.run_id)
    assert first.run_id != second.run_id


def test_REQ_001_3_begin_run_sets_running_and_clears_the_error() -> None:
    """REQ-001.3: a starting run is ``running`` and the previous error is cleared."""
    failed = ConversationState.initial(CONFIG).with_(
        run_status=RunStatus.ERROR, error="boom", error_code=ErrorCode.AGENT_RUN_ERROR
    )
    conv = begin_run(failed, user_text="retry", config=CONFIG)
    assert conv.run_status is RunStatus.RUNNING
    assert conv.error == ""
    assert conv.error_code is None


def test_REQ_002_1_begin_run_creates_the_thread_id_lazily() -> None:
    """REQ-002.1: the first run of a thread generates a UUID4 ``thread_id``."""
    conv = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    assert _is_uuid4(conv.thread_id)


def test_REQ_002_2_begin_run_keeps_the_thread_id() -> None:
    """REQ-002.2: later runs of the thread reuse its ``thread_id``."""
    first = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    second = begin_run(first.with_(run_status=RunStatus.IDLE), user_text="b", config=CONFIG)
    assert second.thread_id == first.thread_id


def test_REQ_010_2_user_run_starts_a_new_turn_of_run_ids() -> None:
    """REQ-010.2: a user-initiated run resets ``last_run_ids`` to itself."""
    first = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    second = begin_run(first.with_(run_status=RunStatus.IDLE), user_text="b", config=CONFIG)
    assert second.last_run_ids == (second.run_id,)


def test_REQ_010_2_follow_up_run_extends_the_turn() -> None:
    """REQ-010.2: a follow-up run (no new user text) keeps the turn's earlier run IDs."""
    first = begin_run(ConversationState.initial(CONFIG), user_text="a", config=CONFIG)
    follow_up = begin_run(first, resume=True, config=CONFIG)
    assert follow_up.last_run_ids == (first.run_id, follow_up.run_id)
    assert len(follow_up.messages) == 1


def test_DM_3_9_begin_run_installs_the_run_config() -> None:
    """DM §3.9: the ``ReducerConfig`` is (re)built once per run."""
    conv = begin_run(ConversationState.initial(ReducerConfig()), user_text="a", config=CONFIG)
    assert conv.config is CONFIG


def test_REQ_005_2_begin_run_accepts_injected_ids() -> None:
    """REQ-005.2: ID generation can be injected, so command sequences are reproducible."""
    ids = iter(["t-1", "r-1", "m-1"])
    conv = begin_run(
        ConversationState.initial(CONFIG),
        user_text="a",
        config=CONFIG,
        new_id=lambda: next(ids),
    )
    assert (conv.thread_id, conv.run_id, conv.messages[0].id) == ("t-1", "r-1", "m-1")
