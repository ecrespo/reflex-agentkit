"""``RunDriver``: client-tool rounds (T-028, TD Flow B and C.4, REQ-018, DD-009)."""

from __future__ import annotations

import asyncio
import time

from helpers.fake_clients import Hang, ScriptedClient, Step, finished, started, text, tool_call
from helpers.fake_state_access import FakeStateAccess
from helpers.invariants import check_invariants

from reflex_agentkit.core.commands import apply_approval, apply_rejection, begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import ReducerConfig, RunStatus, ToolCallStatus
from reflex_agentkit.core.tools import ClientTool, client_tool
from reflex_agentkit.state._driver import DriverSettings, RunDriver
from reflex_agentkit.state._registry import RunRegistry

TOKEN = "tok"  # noqa: S105 - a Reflex session id, not a secret

calls_seen: list[tuple[str, object]] = []


@client_tool
async def pick(day: int) -> str:
    """Pick a day."""
    calls_seen.append(("pick", day))
    await asyncio.sleep(0.05)
    return f"day-{day}"


@client_tool
def pick_sync(day: int) -> str:
    """Pick a day, synchronously."""
    calls_seen.append(("pick_sync", day))
    time.sleep(0.05)
    return f"sync-{day}"


@client_tool(requires_approval=True)
async def confirm(amount: int) -> str:
    """Confirm a payment."""
    calls_seen.append(("confirm", amount))
    return f"paid {amount}"


@client_tool
async def boom() -> str:
    """Always fails."""
    raise ValueError("handler exploded")


@client_tool(timeout_s=0.05)
async def slow() -> str:
    """Never finishes in time."""
    await asyncio.sleep(5)
    return "late"


@client_tool
async def forever() -> str:
    """Runs until cancelled."""
    await asyncio.Event().wait()
    return "never"


TOOLS: tuple[ClientTool, ...] = (pick, pick_sync, confirm, boom, slow, forever)
CONFIG = ReducerConfig(client_tool_names=frozenset(t.name for t in TOOLS))


def _conv() -> ConversationState:
    ids = iter(["thread-1", "run-1", "user-msg-1"])
    return begin_run(
        ConversationState.initial(CONFIG), config=CONFIG, user_text="go", new_id=ids.__next__
    )


class _Run:
    def __init__(
        self,
        *scripts: list[Step],
        conv: ConversationState | None = None,
        max_rounds: int = 8,
    ) -> None:
        calls_seen.clear()
        self.conv = conv if conv is not None else _conv()
        self.access = FakeStateAccess(self.conv, client_token=TOKEN)
        self.client = ScriptedClient(*scripts)
        self.registry = RunRegistry()
        self.ended: list[RunStatus] = []

        async def on_run_end(status: RunStatus) -> None:
            self.ended.append(status)

        self.driver = RunDriver(
            self.access,
            client_factory=lambda: self.client,
            settings=DriverSettings(
                reducer_config=CONFIG,
                flush_interval_ms=0,
                client_tools=TOOLS,
                max_client_tool_rounds=max_rounds,
            ),
            on_run_end=on_run_end,
            registry=self.registry,
            client_token=TOKEN,
        )

    def start(self) -> asyncio.Task[None]:
        return asyncio.create_task(self.driver.run(self.conv))

    async def run(self) -> ConversationState:
        await asyncio.wait_for(self.start(), 5)
        return self.access.conv


def _calls_round(*calls: list[Step]) -> list[Step]:
    return [started(), *text("m1", "let me check"), *(e for c in calls for e in c), finished()]


REPLY: list[Step] = [started(), *text("m2", "done"), finished()]


async def test_REQ_018_2_handler_runs_and_a_follow_up_run_sends_the_result() -> None:
    """REQ-018.2, Flow B.3-5: the result is stored and sent in a follow-up run."""
    run = _Run(_calls_round(tool_call("c1", "pick", '{"day": 3}')), REPLY)
    conv = await run.run()
    assert calls_seen == [("pick", 3)]
    assert conv.run_status is RunStatus.IDLE
    call = conv.tool_calls[0]
    assert (call.status, call.result) == (ToolCallStatus.DONE, "day-3")
    assert len(run.client.inputs) == 2
    follow_up = run.client.inputs[1]
    assert follow_up.run_id != "run-1"
    assert follow_up.thread_id == "thread-1"
    tool_messages = [m for m in follow_up.messages if m.role == "tool"]
    assert [(m.tool_call_id, m.content) for m in tool_messages] == [("c1", "day-3")]
    assert conv.messages[-1].content == "done"
    assert run.ended == [RunStatus.IDLE]
    assert len(run.registry) == 0
    check_invariants(conv)


async def test_REQ_018_2_status_stays_running_through_the_round() -> None:
    """DD-009: no published state between the two runs is ``idle``."""
    run = _Run(_calls_round(tool_call("c1", "pick", '{"day": 3}')), REPLY)
    await run.run()
    statuses = [c.run_status for c in run.access.published]
    assert statuses[-1] is RunStatus.IDLE
    assert all(s is RunStatus.RUNNING for s in statuses[:-1])


async def test_REQ_018_2_handlers_run_concurrently() -> None:
    """Flow B.3: several calls (async and sync) run together, not one after another."""
    run = _Run(
        _calls_round(
            tool_call("c1", "pick", '{"day": 1}'),
            tool_call("c2", "pick", '{"day": 2}'),
            tool_call("c3", "pick_sync", '{"day": 3}'),
        ),
        REPLY,
    )
    began = time.monotonic()
    conv = await run.run()
    assert time.monotonic() - began < 0.14  # three 50 ms handlers, run concurrently
    assert [c.result for c in conv.tool_calls] == ["day-1", "day-2", "sync-3"]
    assert len(run.client.inputs) == 2


async def test_REQ_018_4_handler_error_is_a_tool_result_and_the_run_continues() -> None:
    """REQ-018.4: a raising handler sets ``error`` and the error text is sent."""
    run = _Run(_calls_round(tool_call("c1", "boom", "{}")), REPLY)
    conv = await run.run()
    call = conv.tool_calls[0]
    assert call.status is ToolCallStatus.ERROR
    assert "handler exploded" in (call.result or "")
    assert conv.run_status is RunStatus.IDLE
    sent = [m for m in run.client.inputs[1].messages if m.role == "tool"]
    assert sent[0].content == call.result


async def test_REQ_018_5_handler_timeout_is_an_error_result() -> None:
    """REQ-018.5: a handler past its timeout is treated as raising a timeout error."""
    run = _Run(_calls_round(tool_call("c1", "slow", "{}")), REPLY)
    began = time.monotonic()
    conv = await run.run()
    assert time.monotonic() - began < 1
    call = conv.tool_calls[0]
    assert call.status is ToolCallStatus.ERROR
    assert "timed out" in (call.result or "")
    assert conv.run_status is RunStatus.IDLE


async def test_REQ_018_4_invalid_args_are_an_error_result() -> None:
    """REQ-018.4: arguments that do not validate fail the call, not the run."""
    run = _Run(_calls_round(tool_call("c1", "pick", '{"day": "soon"}')), REPLY)
    conv = await run.run()
    assert conv.tool_calls[0].status is ToolCallStatus.ERROR
    assert calls_seen == []
    assert conv.run_status is RunStatus.IDLE


async def test_REQ_018_3_approval_required_tool_pauses_locally() -> None:
    """REQ-018.3, Flow B.2: the call waits for ``approve_tool``; the task ends."""
    run = _Run(_calls_round(tool_call("c1", "confirm", '{"amount": 5}')), REPLY)
    conv = await run.run()
    assert calls_seen == []
    assert conv.run_status is RunStatus.AWAITING_INPUT
    assert conv.tool_calls[0].status is ToolCallStatus.PENDING_APPROVAL
    assert [i.id for i in conv.interrupts] == ["local-c1"]
    assert conv.interrupts[0].is_local
    assert len(run.client.inputs) == 1
    assert run.ended == [RunStatus.AWAITING_INPUT]
    assert len(run.registry) == 0
    check_invariants(conv)


async def test_REQ_018_3_other_tools_run_before_the_local_pause() -> None:
    """Flow B.2-3: tools without approval run; the approval-required one waits."""
    run = _Run(
        _calls_round(
            tool_call("c1", "pick", '{"day": 4}'),
            tool_call("c2", "confirm", '{"amount": 5}'),
        ),
        REPLY,
    )
    conv = await run.run()
    assert calls_seen == [("pick", 4)]
    first, second = conv.tool_calls
    assert (first.status, first.result) == (ToolCallStatus.DONE, "day-4")
    assert second.status is ToolCallStatus.PENDING_APPROVAL
    assert conv.run_status is RunStatus.AWAITING_INPUT
    assert len(run.client.inputs) == 1


async def test_REQ_018_3_approved_client_tool_runs_with_edited_args_then_follows_up() -> None:
    """Flow C.4: after ``approve_tool`` the handler runs first, then the follow-up run."""
    first = _Run(_calls_round(tool_call("c1", "confirm", '{"amount": 5}')))
    paused = await first.run()
    resumed = begin_run(apply_approval(paused, "c1", {"amount": 7}), config=CONFIG, resume=True)
    run = _Run(REPLY, conv=resumed)
    conv = await run.run()
    assert calls_seen == [("confirm", 7)]
    call = conv.tool_calls[0]
    assert (call.status, call.result) == (ToolCallStatus.DONE, "paid 7")
    assert len(run.client.inputs) == 1  # the approval never round-trips to the agent
    sent = run.client.inputs[0]
    assert sent.resume in (None, [])
    assert [(m.tool_call_id, m.content) for m in sent.messages if m.role == "tool"] == [
        ("c1", "paid 7")
    ]
    assert conv.run_status is RunStatus.IDLE


async def test_REQ_018_3_rejected_client_tool_sends_the_rejection_without_running() -> None:
    """REQ-018.3: on ``reject_tool`` the rejection result is sent; the handler never runs."""
    first = _Run(_calls_round(tool_call("c1", "confirm", '{"amount": 5}')))
    paused = await first.run()
    resumed = begin_run(apply_rejection(paused, "c1", "too much"), config=CONFIG, resume=True)
    run = _Run(REPLY, conv=resumed)
    conv = await run.run()
    assert calls_seen == []
    assert conv.tool_calls[0].status is ToolCallStatus.REJECTED
    sent = [m for m in run.client.inputs[0].messages if m.role == "tool"]
    assert str(sent[0].content).startswith("Rejected by the user")
    assert conv.run_status is RunStatus.IDLE


async def test_DD_009_loop_limit_ends_in_error() -> None:
    """DD-009: a model that keeps calling client tools is stopped."""
    run = _Run(REPLY, max_rounds=2)
    # Every run calls the tool again with a fresh call ID.
    run.client.scripts = [
        _calls_round(tool_call(f"c{i}", "pick", '{"day": 1}')) for i in range(1, 6)
    ]
    conv = await run.run()
    assert conv.run_status is RunStatus.ERROR
    assert conv.error_code is ErrorCode.CLIENT_TOOL_LOOP_LIMIT
    assert len(run.client.inputs) == 3  # the first run plus two follow-ups
    assert run.ended == [RunStatus.ERROR]
    assert len(run.registry) == 0
    check_invariants(conv)


async def test_DD_009_follow_up_run_is_registered_for_cancellation() -> None:
    """Flow B.5, D.1: the follow-up run is cancellable through the registry."""
    run = _Run(_calls_round(tool_call("c1", "pick", '{"day": 3}')), [started(), Hang()])
    task = run.start()
    for _ in range(100):
        if len(run.client.inputs) == 2:
            break
        await asyncio.sleep(0.01)
    follow_up_id = run.client.inputs[1].run_id
    assert run.access.conv.run_id == follow_up_id
    run.access.cancel_requested = follow_up_id
    assert run.registry.cancel(TOKEN, follow_up_id) is True
    await asyncio.wait_for(task, 1)
    assert run.access.conv.run_status is RunStatus.CANCELLED
    assert run.ended == [RunStatus.CANCELLED]
    assert len(run.registry) == 0


async def test_REQ_007_1_cancel_during_a_handler_fails_the_call() -> None:
    """REQ-007.1, 007.4: a cancel while a handler runs ends ``cancelled`` within 1 s."""
    run = _Run(_calls_round(tool_call("c1", "forever", "{}")), REPLY)
    task = run.start()
    for _ in range(100):
        if run.access.conv.tool_calls:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    began = time.monotonic()
    run.access.cancel_requested = "run-1"  # the flag path: another worker's cancel
    await asyncio.wait_for(task, 1)
    assert time.monotonic() - began < 1
    conv = run.access.conv
    assert conv.run_status is RunStatus.CANCELLED
    assert conv.tool_calls[0].status is ToolCallStatus.ERROR
    assert len(run.client.inputs) == 1
    assert run.ended == [RunStatus.CANCELLED]


async def test_REQ_026_2_replaced_conversation_during_a_handler_writes_nothing() -> None:
    """REQ-026.2: if the state moved on while a handler ran, the round stops silently."""
    run = _Run(_calls_round(tool_call("c1", "forever", "{}")), REPLY)
    task = run.start()
    for _ in range(100):
        if run.access.conv.tool_calls:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)
    replaced = ConversationState.initial(CONFIG)
    run.access.conv = replaced
    await asyncio.wait_for(task, 1)
    assert run.access.conv is replaced
    assert run.ended == []
    assert len(run.client.inputs) == 1
