"""``RunDriver``: cancellation (T-027, TD Flow D, REQ-007)."""

from __future__ import annotations

import asyncio
import time

from ag_ui.core import TextMessageContentEvent, ToolCallStartEvent
from helpers.fake_clients import Hang, ScriptedClient, Sleep, Step, finished, started, text
from helpers.fake_state_access import FakeStateAccess
from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import CANCELLED_RESULT, begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import ReducerConfig, RunStatus, ToolCallStatus
from reflex_agentkit.state._driver import DriverSettings, RunDriver
from reflex_agentkit.state._registry import RunRegistry

CONFIG = ReducerConfig()
TOKEN = "tok"  # noqa: S105 - a Reflex session id, not a secret


def _conv() -> ConversationState:
    ids = iter(["thread-1", "run-1", "user-msg-1"])
    return begin_run(
        ConversationState.initial(CONFIG), config=CONFIG, user_text="go", new_id=ids.__next__
    )


def _start(
    script: list[Step], *, flush_interval_ms: int = 50
) -> tuple[FakeStateAccess, ScriptedClient, RunRegistry, list[RunStatus], asyncio.Task[None]]:
    conv = _conv()
    access = FakeStateAccess(conv, client_token=TOKEN)
    client = ScriptedClient(script)
    registry = RunRegistry()
    ended: list[RunStatus] = []

    async def on_run_end(status: RunStatus) -> None:
        ended.append(status)

    driver = RunDriver(
        access,
        client_factory=lambda: client,
        settings=DriverSettings(reducer_config=CONFIG, flush_interval_ms=flush_interval_ms),
        on_run_end=on_run_end,
        registry=registry,
        client_token=TOKEN,
    )
    return access, client, registry, ended, asyncio.create_task(driver.run(conv))


PARTIAL: list[Step] = [
    started(),
    *text("m1", "partial")[:2],
    ToolCallStartEvent(tool_call_id="c1", tool_call_name="search", parent_message_id="m1"),
]


async def test_REQ_007_1_registry_path_cancels_immediately() -> None:
    """Flow D.1-2: a same-worker cancel stops the run at once and publishes ``cancelled``."""
    access, client, registry, ended, task = _start([*PARTIAL, Hang()])
    await asyncio.wait_for(access.first_publish.wait(), 1)
    began = time.monotonic()
    access.cancel_requested = "run-1"
    assert registry.cancel(TOKEN, "run-1") is True
    await asyncio.wait_for(task, 1)  # the driver swallows the CancelledError
    assert time.monotonic() - began < 0.5
    assert access.conv.run_status is RunStatus.CANCELLED
    assert client.cancelled
    assert ended == [RunStatus.CANCELLED]
    assert len(registry) == 0


async def test_REQ_007_4_partial_content_is_kept_and_open_calls_fail() -> None:
    """REQ-007.4: partial text stays; streaming calls end in ``error`` "cancelled"."""
    access, _, registry, _, task = _start([*PARTIAL, Hang()])
    await asyncio.wait_for(access.first_publish.wait(), 1)
    access.cancel_requested = "run-1"
    registry.cancel(TOKEN, "run-1")
    await asyncio.wait_for(task, 1)
    message = access.conv.messages[-1]
    assert (message.content, message.streaming) == ("partial", False)
    call = access.conv.tool_calls[0]
    assert (call.status, call.result) == (ToolCallStatus.ERROR, CANCELLED_RESULT)
    check_invariants(access.conv)


async def test_REQ_007_1_flag_path_with_silent_upstream_under_1s() -> None:
    """Flow D.3: another worker's cancel is seen at the next tick, even if nothing arrives."""
    access, client, _, ended, task = _start([*PARTIAL, Hang()], flush_interval_ms=0)
    await asyncio.wait_for(access.first_publish.wait(), 1)
    await asyncio.sleep(0.05)
    began = time.monotonic()
    access.cancel_requested = "run-1"  # set through another worker: no registry hit
    await asyncio.wait_for(task, 1)
    assert time.monotonic() - began < 1.0
    assert access.conv.run_status is RunStatus.CANCELLED
    assert access.conv.messages[-1].content == "partial"
    assert client.cancelled
    assert ended == [RunStatus.CANCELLED]


async def test_REQ_007_5_events_after_the_cancel_are_discarded() -> None:
    """REQ-007.5: once the cancel is seen, nothing more is applied or published."""
    access, _, _, _, task = _start(
        [
            started(),
            *text("m1", "kept")[:2],
            Sleep(0.3),
            TextMessageContentEvent(message_id="m1", delta=" dropped"),
            finished(),
        ]
    )
    access.cancel_requested = "run-1"
    await asyncio.wait_for(task, 1)
    assert access.conv.run_status is RunStatus.CANCELLED
    assert access.conv.messages[-1].content == "kept"
    assert access.published[-1] is access.conv
    assert all(c.run_status is not RunStatus.IDLE for c in access.published)


async def test_REQ_007_1_a_cancel_for_another_run_is_ignored() -> None:
    """Only a cancel naming this run stops it."""
    access, _, _, _, task = _start([started(), Sleep(0.15), finished()], flush_interval_ms=10)
    access.cancel_requested = "some-older-run"
    await asyncio.wait_for(task, 1)
    assert access.conv.run_status is RunStatus.IDLE


async def test_TD_E_worker_shutdown_ends_in_error() -> None:
    """Flow E: a task cancelled without a cancel request (shutdown) ends in ``error``."""
    access, client, _, ended, task = _start([*PARTIAL, Hang()])
    await asyncio.wait_for(access.first_publish.wait(), 1)
    task.cancel()
    await asyncio.wait_for(task, 1)
    assert access.conv.run_status is RunStatus.ERROR
    assert access.conv.error_code is ErrorCode.AGENT_STREAM_ERROR
    assert "shutting down" in access.conv.error
    assert access.conv.messages[-1].content == "partial"
    assert client.cancelled
    assert ended == [RunStatus.ERROR]


async def test_REQ_026_2_cancel_after_the_state_was_replaced_writes_nothing() -> None:
    """A cancelled driver whose conversation was replaced leaves the new one alone."""
    access, _, registry, ended, task = _start([*PARTIAL, Hang()])
    await asyncio.wait_for(access.first_publish.wait(), 1)
    replacement = ConversationState.initial(CONFIG)
    access.conv = replacement
    registry.cancel(TOKEN, "run-1")
    await asyncio.wait_for(task, 1)
    assert access.conv is replacement
    assert ended == []
