"""``RunDriver``: streaming, batching, ownership and failure mapping (T-026, TD Flows A, E)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import pytest
from ag_ui.core import TextMessageContentEvent, TextMessageEndEvent
from helpers.fake_clients import (
    Hang,
    Raise,
    ScriptedClient,
    Sleep,
    Step,
    custom,
    finished,
    run_error,
    started,
    text,
)
from helpers.fake_state_access import FakeStateAccess
from helpers.invariants import check_invariants

from reflex_agentkit.core.clients.base import AgentClient
from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import AgentHTTPError, AgentStreamError, ErrorCode
from reflex_agentkit.core.models import CustomEventRecord, ReducerConfig, RunStatus
from reflex_agentkit.state._driver import DriverSettings, RunDriver
from reflex_agentkit.state._registry import RunRegistry

CONFIG = ReducerConfig()
SECRET_TEXT = "the user's private words"


def _conv() -> ConversationState:
    ids = iter(["thread-1", "run-1", "user-msg-1"])
    return begin_run(
        ConversationState.initial(CONFIG), config=CONFIG, user_text=SECRET_TEXT, new_id=ids.__next__
    )


def _driver(
    access: FakeStateAccess,
    client: AgentClient | Exception,
    *,
    flush_interval_ms: int = 50,
    registry: RunRegistry | None = None,
    flushed: list[list[CustomEventRecord]] | None = None,
    ended: list[RunStatus] | None = None,
) -> RunDriver:
    def factory() -> AgentClient:
        if isinstance(client, Exception):
            raise client
        return client

    async def on_flush(events: list[CustomEventRecord]) -> None:
        if flushed is not None:
            flushed.append(events)

    async def on_run_end(status: RunStatus) -> None:
        if ended is not None:
            ended.append(status)

    return RunDriver(
        access,
        client_factory=factory,
        settings=DriverSettings(flush_interval_ms=flush_interval_ms, reducer_config=CONFIG),
        on_flush=on_flush,
        on_run_end=on_run_end,
        registry=registry or RunRegistry(),
    )


async def _run(script: Sequence[Step], **kwargs: object) -> tuple[FakeStateAccess, ScriptedClient]:
    conv = _conv()
    access = FakeStateAccess(conv)
    client = ScriptedClient(script)
    await asyncio.wait_for(_driver(access, client, **kwargs).run(conv), 5)  # type: ignore[arg-type]
    return access, client


async def test_REQ_001_2_streams_a_reply_into_the_state() -> None:
    """Flow A: the reply is reduced and published; the run ends ``idle``."""
    access, client = await _run([started(), *text("m1", "Hel", "lo"), finished()])
    assert access.conv.run_status is RunStatus.IDLE
    assert access.conv.messages[-1].content == "Hello"
    assert client.inputs[0].run_id == "run-1"
    assert client.inputs[0].messages[0].content == SECRET_TEXT
    assert client.closed == 1
    check_invariants(access.conv)


async def test_REQ_006_3_push_rate_bounded() -> None:
    """REQ-006.3: 1,000 deltas in ~1 s with a 50 ms interval → ≤ 25 publishes per second."""
    deltas: list[Step] = []
    for i in range(1000):
        deltas.append(TextMessageContentEvent(message_id="m1", delta="x"))
        if i % 10 == 9:
            deltas.append(Sleep(0.01))
    script = [started(), *text("m1")[:1], *deltas, TextMessageEndEvent(message_id="m1"), finished()]
    access, _ = await _run(script)
    assert access.conv.messages[-1].content == "x" * 1000
    times = access.publish_times
    worst = max(sum(1 for t in times if start <= t < start + 1.0) for start in times)
    assert worst <= 25, f"{worst} publishes in one second ({len(times)} in total)"


async def test_REQ_006_4_interval_zero_publishes_every_event() -> None:
    """REQ-006.4: ``flush_interval_ms=0`` pushes one update per event."""
    script = [started(), *text("m1", "a", "b", "c"), finished()]
    access, _ = await _run(script, flush_interval_ms=0)
    assert access.publishes == 7


async def test_REQ_006_2_terminal_event_flushes_immediately() -> None:
    """REQ-006.2: the end of a run is pushed at once, not at the next deadline."""
    access, _ = await asyncio.wait_for(
        _run([started(), *text("m1", "hi"), finished(), Hang()], flush_interval_ms=10_000), 1
    )
    assert access.publishes == 1
    assert access.conv.run_status is RunStatus.IDLE


async def test_REQ_006_1_events_are_applied_between_publishes() -> None:
    """REQ-006.1: every event is reduced; only the pushes are batched."""
    access, _ = await _run(
        [started(), *text("m1", *"abcdef"), finished()], flush_interval_ms=10_000
    )
    assert access.published[-1].messages[-1].content == "abcdef"


async def test_REQ_026_2_ownership_lost_stops_and_closes_upstream() -> None:
    """REQ-026.2: a replaced conversation (new thread, expired state) stops the driver silently."""
    conv = _conv()
    access = FakeStateAccess(conv)
    client = ScriptedClient([started(), *text("m1", "a"), Sleep(0.05), *text("m2", "b"), Hang()])
    driver = _driver(access, client, flush_interval_ms=10)
    task = asyncio.create_task(driver.run(conv))
    while not access.published:
        await asyncio.sleep(0.005)
    replacement = ConversationState.initial(CONFIG).with_(thread_id="new-thread")
    access.conv = replacement
    await asyncio.wait_for(task, 1)
    assert access.conv is replacement
    assert client.cancelled
    assert client.closed == 1


async def test_REQ_004_3_run_error_event_ends_in_error() -> None:
    """REQ-004.3: ``RUN_ERROR`` → ``error`` with the agent's message; content kept."""
    access, _ = await _run([started(), *text("m1", "partial")[:2], run_error("model overloaded")])
    assert (access.conv.run_status, access.conv.error_code, access.conv.error) == (
        RunStatus.ERROR,
        ErrorCode.AGENT_RUN_ERROR,
        "model overloaded",
    )
    assert access.conv.messages[-1].content == "partial"


@pytest.mark.parametrize(
    ("error", "code", "fragment"),
    [
        (AgentHTTPError(503), ErrorCode.AGENT_HTTP_ERROR, "503"),
        (AgentStreamError("timeout", "read timeout"), ErrorCode.AGENT_STREAM_ERROR, "read timeout"),
        (AgentStreamError("eof"), ErrorCode.AGENT_STREAM_ERROR, "eof"),
        (
            AgentStreamError("agent_raised", "the agent raised KeyError"),
            ErrorCode.AGENT_EXCEPTION,
            "KeyError",
        ),
        (ValueError("client bug"), ErrorCode.AGENT_EXCEPTION, "ValueError"),
    ],
    ids=["http", "timeout", "eof", "agent-raised", "unexpected"],
)
async def test_REQ_021_3_failures_map_to_error_codes(
    error: Exception, code: ErrorCode, fragment: str
) -> None:
    """TD Flow E: transport failures become ``error`` + code; partial content is kept."""
    access, _ = await _run([started(), *text("m1", "partial")[:2], Raise(error)])
    assert access.conv.run_status is RunStatus.ERROR
    assert access.conv.error_code is code
    assert fragment in access.conv.error
    assert access.conv.messages[-1].content == "partial"
    assert access.conv.messages[-1].streaming is False
    check_invariants(access.conv)


async def test_REQ_004_4_stream_ending_without_a_terminal_event_is_an_error() -> None:
    """REQ-004.4: a client whose stream simply ends is treated as an unexpected EOF."""
    access, _ = await _run([started(), *text("m1", "a")])
    assert access.conv.error_code is ErrorCode.AGENT_STREAM_ERROR


async def test_REQ_021_create_client_failure_is_an_agent_exception() -> None:
    """TD Flow E: ``create_client()`` raising ends the run with ``AGENT_EXCEPTION``."""
    conv = _conv()
    access = FakeStateAccess(conv)
    ended: list[RunStatus] = []
    await _driver(access, RuntimeError("no credentials"), ended=ended).run(conv)
    assert access.conv.error_code is ErrorCode.AGENT_EXCEPTION
    assert "RuntimeError" in access.conv.error
    assert ended == [RunStatus.ERROR]


async def test_REQ_020_custom_events_reach_on_flush_once() -> None:
    """REQ-020: each CUSTOM event is handed to the hook once, at the flush after it."""
    flushed: list[list[CustomEventRecord]] = []
    await _run(
        [started(), custom("a", 1), Sleep(0.03), custom("b", 2), custom("c", 3), finished()],
        flush_interval_ms=10,
        flushed=flushed,
    )
    names = [[e.name for e in batch] for batch in flushed]
    assert [n for batch in names for n in batch] == ["a", "b", "c"]
    assert len(flushed) >= 2


async def test_REQ_020_on_run_end_runs_once_with_the_final_status() -> None:
    ended: list[RunStatus] = []
    await _run([started(), finished()], ended=ended)
    assert ended == [RunStatus.IDLE]


async def test_REQ_027_1_diagnostics_are_logged_with_run_context_and_cleared(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """REQ-027.1: reducer diagnostics are logged with ``thread_id``/``run_id``, then dropped."""
    with caplog.at_level(logging.DEBUG, logger="reflex_agentkit"):
        access, _ = await _run([started(), TextMessageEndEvent(message_id="ghost"), finished()])
    records = [r for r in caplog.records if "ghost" in r.getMessage()]
    assert records
    assert all((r.thread_id, r.run_id) == ("thread-1", "run-1") for r in records)  # type: ignore[attr-defined]
    assert all(conv.diagnostics == () for conv in access.published)


async def test_REQ_027_2_no_content_above_debug(caplog: pytest.LogCaptureFixture) -> None:
    """REQ-027.2: message text never appears in records at INFO or above."""
    with caplog.at_level(logging.DEBUG, logger="reflex_agentkit"):
        await _run([started(), *text("m1", SECRET_TEXT), finished()])
        await _run([started(), Raise(ValueError(SECRET_TEXT))])
    loud = [r for r in caplog.records if r.levelno >= logging.INFO]
    assert loud, "the run summary is logged at INFO"
    for record in loud:
        assert SECRET_TEXT not in record.getMessage()
        assert SECRET_TEXT not in str(record.exc_info)
        assert record.thread_id == "thread-1"  # type: ignore[attr-defined]


async def test_REQ_007_run_is_registered_while_it_streams() -> None:
    """Flow A.4: the driver task is in the registry during the run and removed after."""
    conv = _conv()
    access = FakeStateAccess(conv)
    registry = RunRegistry()
    client = ScriptedClient([started(), Sleep(0.05), finished()])
    task = asyncio.create_task(_driver(access, client, registry=registry).run(conv))
    await asyncio.sleep(0.02)
    assert len(registry) == 1
    await task
    assert len(registry) == 0
