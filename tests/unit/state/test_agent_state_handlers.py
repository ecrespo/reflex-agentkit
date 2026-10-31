"""``AgentState`` handlers and hooks, through Reflex's event processor (T-030, API §4.3-4.4)."""

from __future__ import annotations

import asyncio
import time
from typing import Any, ClassVar

import pydantic
import reflex as rx
from ag_ui.core import RunAgentInput, StateSnapshotEvent
from helpers.fake_clients import (
    Hang,
    ScriptedClient,
    Step,
    custom,
    finished,
    run_error,
    started,
    text,
    tool_call,
)
from helpers.reflex_harness import ReflexHarness

from reflex_agentkit import AgentState
from reflex_agentkit.core.clients.base import AgentClient
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import RunStatus, ToolCallStatus
from reflex_agentkit.core.tools import client_tool

HELLO: list[Step] = [started(), *text("m1", "hello"), finished()]


def _approval_pause(call_id: str = "c1") -> list[Step]:
    outcome = {
        "type": "interrupt",
        "interrupts": [{"id": f"int-{call_id}", "reason": "tool_call", "toolCallId": call_id}],
    }
    return [started(), *tool_call(call_id, "book", '{"city": "Lisbon"}'), finished(outcome)]


GENERIC_PAUSE: list[Step] = [
    started(),
    finished(
        {"type": "interrupt", "interrupts": [{"id": "i1", "reason": "confirm", "message": "Sure?"}]}
    ),
]


def _state_class(name: str, client: ScriptedClient, **config: Any) -> type[AgentState]:
    """A fresh ``AgentState`` subclass whose ``agent`` is ``client``."""
    annotations = {"agent": "ClassVar", **dict.fromkeys(config, "ClassVar")}
    namespace = {"__annotations__": annotations, "agent": client, "__module__": __name__, **config}
    return type(name, (AgentState, rx.State), namespace)


async def _wait_for(predicate: Any, wait_s: float = 2.0) -> None:
    deadline = time.monotonic() + wait_s
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


async def _wait_status(
    rx_: ReflexHarness, token: str, cls: type[AgentState], status: RunStatus
) -> AgentState:
    deadline = time.monotonic() + 2
    while True:
        state = await rx_.state(token, cls)
        if state.run_status == status:
            return state
        if time.monotonic() > deadline:
            raise AssertionError(f"status is {state.run_status}, not {status}")
        await asyncio.sleep(0.01)


# --- send_message (REQ-001) ---------------------------------------------------------------


async def test_REQ_001_1_send_message_streams_the_reply(reflex_harness: ReflexHarness) -> None:
    """REQ-001.1-3, REQ-002.1: the user message, a run with a new thread, the reply."""
    client = ScriptedClient(HELLO)
    cls = _state_class("SendState", client)
    await reflex_harness.call("tok", cls, "send_message", text="  hi  ")
    state = await reflex_harness.state("tok", cls)
    assert [(m.role, m.content) for m in state.messages] == [("user", "hi"), ("assistant", "hello")]
    assert state.run_status == RunStatus.IDLE
    assert state.thread_id
    assert state.run_id == client.inputs[0].run_id
    sent = client.inputs[0]
    assert sent.thread_id == state.thread_id
    assert [m.content for m in sent.messages] == ["hi"]
    assert reflex_harness.deltas_for("tok")


async def test_REQ_002_2_the_thread_id_is_kept_across_runs(reflex_harness: ReflexHarness) -> None:
    """REQ-002.2: every run of the thread sends the same ``thread_id``."""
    client = ScriptedClient(HELLO)
    cls = _state_class("ThreadState", client)
    await reflex_harness.call("tok", cls, "send_message", text="one")
    await reflex_harness.call("tok", cls, "send_message", text="two")
    first, second = client.inputs
    assert first.thread_id == second.thread_id
    assert first.run_id != second.run_id
    assert [m.content for m in second.messages] == ["one", "hello", "two"]


async def test_REQ_001_4_empty_text_is_ignored(reflex_harness: ReflexHarness) -> None:
    """REQ-001.4: empty or whitespace-only text changes nothing."""
    client = ScriptedClient(HELLO)
    cls = _state_class("EmptyState", client)
    await reflex_harness.call("tok", cls, "send_message", text="   ")
    state = await reflex_harness.state("tok", cls)
    assert (state.messages, state.run_status) == ([], RunStatus.IDLE)
    assert client.inputs == []


async def test_REQ_001_5_too_long_text_is_rejected(reflex_harness: ReflexHarness) -> None:
    """REQ-001.5: the error names the limit; messages are unchanged."""
    client = ScriptedClient(HELLO)
    cls = _state_class("LongState", client, max_message_length=5)
    await reflex_harness.call("tok", cls, "send_message", text="toolong")
    state = await reflex_harness.state("tok", cls)
    assert state.messages == []
    assert state.error_code == ErrorCode.MESSAGE_TOO_LONG
    assert "5" in state.error
    assert client.inputs == []


async def test_REQ_001_6_send_while_running_is_ignored(reflex_harness: ReflexHarness) -> None:
    """REQ-001.6: a second message during a run leaves the run alone."""
    client = ScriptedClient([started(), Hang()])
    cls = _state_class("BusyState", client)
    await reflex_harness.start("tok", cls, "send_message", text="one")
    await _wait_for(lambda: len(client.inputs) == 1)
    await reflex_harness.call("tok", cls, "send_message", text="two")
    state = await reflex_harness.state("tok", cls)
    assert [m.content for m in state.messages] == ["one"]
    assert state.run_status == RunStatus.RUNNING
    await reflex_harness.call("tok", cls, "cancel_run")
    await _wait_status(reflex_harness, "tok", cls, RunStatus.CANCELLED)


# --- cancel_run (REQ-007, REQ-015) ---------------------------------------------------------


async def test_REQ_007_1_cancel_run_stops_the_stream(reflex_harness: ReflexHarness) -> None:
    """REQ-007.1, 007.3: the run ends ``cancelled`` within 1 s and the stream is cancelled."""
    client = ScriptedClient([started(), *text("m1", "par")[:2], Hang()])
    cls = _state_class("CancelState", client)
    await reflex_harness.start("tok", cls, "send_message", text="go")
    await _wait_for(lambda: len(client.inputs) == 1)
    began = time.monotonic()
    await reflex_harness.call("tok", cls, "cancel_run")
    state = await _wait_status(reflex_harness, "tok", cls, RunStatus.CANCELLED)
    assert time.monotonic() - began < 1
    assert state.messages[-1].content == "par"
    assert state.messages[-1].streaming is False
    await _wait_for(lambda: client.cancelled)


async def test_REQ_015_2_cancel_while_paused_and_the_next_run_cancels_the_interrupt(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-015.1-3: approvals are rejected; the next run sends ``cancelled`` resume entries."""
    client = ScriptedClient(_approval_pause(), HELLO)
    cls = _state_class("PauseCancelState", client)
    await reflex_harness.call("tok", cls, "send_message", text="book")
    state = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.AWAITING_INPUT
    assert (state.awaiting_input, state.can_send) == (True, False)
    await reflex_harness.call("tok", cls, "send_message", text="ignored")
    assert len(client.inputs) == 1
    await reflex_harness.call("tok", cls, "cancel_run")
    state = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.CANCELLED
    assert state.tool_calls[0].status == ToolCallStatus.REJECTED
    await reflex_harness.call("tok", cls, "send_message", text="again")
    resume = client.inputs[1].resume or []
    assert [(r.interrupt_id, r.status) for r in resume] == [("int-c1", "cancelled")]


async def test_REQ_007_cancel_when_idle_is_a_no_op(reflex_harness: ReflexHarness) -> None:
    """API §4.3: ``cancel_run`` outside ``running``/``awaiting_input`` changes nothing."""
    cls = _state_class("IdleCancelState", ScriptedClient(HELLO))
    await reflex_harness.call("tok", cls, "cancel_run")
    assert (await reflex_harness.state("tok", cls)).run_status == RunStatus.IDLE


# --- approvals and interrupts (REQ-013, REQ-014) -------------------------------------------


async def test_REQ_013_3_approve_with_json_text_resumes_with_edited_args(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-013.2-3, 013.5: a ``str`` edit is parsed; the resume run carries the payload."""
    client = ScriptedClient(_approval_pause(), HELLO)
    cls = _state_class("ApproveState", client)
    await reflex_harness.call("tok", cls, "send_message", text="book")
    state = await reflex_harness.state("tok", cls)
    assert [c.id for c in state.pending_approvals] == ["c1"]
    await reflex_harness.call(
        "tok", cls, "approve_tool", call_id="c1", edited_args='{"city": "Porto"}'
    )
    state = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.IDLE
    resume = client.inputs[1].resume or []
    assert [(r.interrupt_id, r.payload) for r in resume] == [
        ("int-c1", {"approved": True, "editedArgs": {"city": "Porto"}})
    ]


async def test_REQ_013_7_invalid_edited_args_keep_the_call_pending(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-013.7: invalid JSON edits set ``INVALID_EDITED_ARGS``; nothing resumes."""
    client = ScriptedClient(_approval_pause(), HELLO)
    cls = _state_class("BadEditState", client)
    await reflex_harness.call("tok", cls, "send_message", text="book")
    await reflex_harness.call("tok", cls, "approve_tool", call_id="c1", edited_args="{nope")
    state = await reflex_harness.state("tok", cls)
    assert state.error_code == ErrorCode.INVALID_EDITED_ARGS
    assert state.tool_calls[0].status == ToolCallStatus.PENDING_APPROVAL
    assert len(client.inputs) == 1


async def test_REQ_013_6_unknown_call_or_wrong_types_are_ignored(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-013.6, TD §6.1: unknown IDs and forged argument types are no-ops."""
    client = ScriptedClient(_approval_pause(), HELLO)
    cls = _state_class("ForgedApproveState", client)
    await reflex_harness.call("tok", cls, "send_message", text="book")
    await reflex_harness.call("tok", cls, "approve_tool", call_id="ghost")
    await reflex_harness.call("tok", cls, "approve_tool", call_id=["c1"])
    await reflex_harness.call("tok", cls, "reject_tool", call_id="c1", reason=42)
    state = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.AWAITING_INPUT
    assert len(client.inputs) == 1


async def test_REQ_013_4_reject_resumes_with_the_reason(reflex_harness: ReflexHarness) -> None:
    """REQ-013.4: the rejection payload carries the reason."""
    client = ScriptedClient(_approval_pause(), HELLO)
    cls = _state_class("RejectState", client)
    await reflex_harness.call("tok", cls, "send_message", text="book")
    await reflex_harness.call("tok", cls, "reject_tool", call_id="c1", reason="too pricey")
    state = await reflex_harness.state("tok", cls)
    assert state.tool_calls[0].status == ToolCallStatus.REJECTED
    resume = client.inputs[1].resume or []
    assert resume[0].payload == {"approved": False, "reason": "too pricey"}


async def test_REQ_014_2_respond_to_interrupt_resumes(reflex_harness: ReflexHarness) -> None:
    """REQ-014.1-2: the generic interrupt is shown, answered, and the run resumes."""
    client = ScriptedClient(GENERIC_PAUSE, HELLO)
    cls = _state_class("InterruptState", client)
    await reflex_harness.call("tok", cls, "send_message", text="go")
    state = await reflex_harness.state("tok", cls)
    assert state.pending_interrupt is not None
    assert (state.pending_interrupt.id, state.pending_interrupt.message) == ("i1", "Sure?")
    await reflex_harness.call("tok", cls, "respond_to_interrupt", payload='{"ok": true}')
    state = await reflex_harness.state("tok", cls)
    assert state.pending_interrupt is None
    resume = client.inputs[1].resume or []
    assert [(r.interrupt_id, r.payload) for r in resume] == [("i1", {"ok": True})]
    assert state.run_status == RunStatus.IDLE


# --- new_thread (REQ-002) --------------------------------------------------------------------


async def test_REQ_002_3_new_thread_resets_everything(reflex_harness: ReflexHarness) -> None:
    """REQ-002.3: a new thread clears the conversation and gets a new ``thread_id``."""
    client = ScriptedClient(HELLO)
    cls = _state_class("NewThreadState", client)
    await reflex_harness.call("tok", cls, "send_message", text="hi")
    old = (await reflex_harness.state("tok", cls)).thread_id
    await reflex_harness.call("tok", cls, "new_thread")
    state = await reflex_harness.state("tok", cls)
    assert (state.messages, state.tool_calls, state.shared_state) == ([], [], {})
    assert state.run_status == RunStatus.IDLE
    assert state.thread_id
    assert state.thread_id != old


async def test_REQ_002_4_new_thread_while_running_cancels_first(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-002.4: the run is cancelled and writes nothing into the new thread."""
    client = ScriptedClient([started(), *text("m1", "par")[:2], Hang()])
    cls = _state_class("NewThreadRunningState", client)
    await reflex_harness.start("tok", cls, "send_message", text="go")
    await _wait_for(lambda: len(client.inputs) == 1)
    await reflex_harness.call("tok", cls, "new_thread")
    await _wait_for(lambda: client.cancelled)
    await asyncio.sleep(0.1)
    state = await reflex_harness.state("tok", cls)
    assert (state.messages, state.run_status) == ([], RunStatus.IDLE)


# --- shared state (REQ-016.5-6, REQ-017) ---------------------------------------------------


async def test_REQ_017_1_app_writes_reach_the_next_run(reflex_harness: ReflexHarness) -> None:
    """REQ-017.1, 016.7: written state is sent as ``RunAgentInput.state``."""
    client = ScriptedClient(HELLO)
    cls = _state_class("WriteState", client)
    await reflex_harness.call("tok", cls, "set_shared_state", value={"count": 1})
    await reflex_harness.call(
        "tok", cls, "patch_shared_state", ops=[{"op": "replace", "path": "/count", "value": 2}]
    )
    assert (await reflex_harness.state("tok", cls)).shared_state == {"count": 2}
    await reflex_harness.call("tok", cls, "send_message", text="go")
    assert client.inputs[0].state == {"count": 2}


async def test_REQ_017_2_app_write_while_running_is_locked(reflex_harness: ReflexHarness) -> None:
    """REQ-017.2: while running, writes are rejected with ``SHARED_STATE_LOCKED``."""
    client = ScriptedClient([started(), Hang()])
    cls = _state_class("LockedWriteState", client)
    await reflex_harness.start("tok", cls, "send_message", text="go")
    await _wait_for(lambda: len(client.inputs) == 1)
    await reflex_harness.call("tok", cls, "set_shared_state", value={"count": 1})
    state = await reflex_harness.state("tok", cls)
    assert state.shared_state == {}
    assert state.error_code == ErrorCode.SHARED_STATE_LOCKED
    await reflex_harness.call("tok", cls, "cancel_run")
    await _wait_status(reflex_harness, "tok", cls, RunStatus.CANCELLED)


class Counter(pydantic.BaseModel):
    count: int = 0


async def test_REQ_016_5_model_validates_app_writes_and_agent_snapshots(
    reflex_harness: ReflexHarness,
) -> None:
    """REQ-016.5-6: invalid values are rejected; the typed accessor returns the model."""
    script: list[Step] = [
        started(),
        StateSnapshotEvent(snapshot={"count": 3}),
        StateSnapshotEvent(snapshot={"count": "many"}),
        finished(),
    ]
    client = ScriptedClient(script)
    cls = _state_class("ModelState", client, shared_state_model=Counter)
    await reflex_harness.call("tok", cls, "set_shared_state", value={"count": "x"})
    state = await reflex_harness.state("tok", cls)
    assert state.shared_state == {}
    assert state.error_code == ErrorCode.SHARED_STATE_INVALID
    await reflex_harness.call("tok", cls, "send_message", text="go")
    state = await reflex_harness.state("tok", cls)
    assert state.shared_state == {"count": 3}
    assert state.shared_state_stale is True
    assert state.typed_shared_state() == Counter(count=3)


# --- retry_run (REQ-028) ---------------------------------------------------------------------


async def test_REQ_028_1_retry_after_an_error(reflex_harness: ReflexHarness) -> None:
    """REQ-028.1: the last user turn is sent again in a new run."""
    client = ScriptedClient([started(), *text("m1", "par"), run_error("boom")], HELLO)
    cls = _state_class("RetryState", client)
    await reflex_harness.call("tok", cls, "send_message", text="go")
    state = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.ERROR
    await reflex_harness.call("tok", cls, "retry_run")
    state = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.IDLE
    assert [m.content for m in client.inputs[1].messages] == ["go"]
    assert [m.content for m in state.messages] == ["go", "hello"]


async def test_REQ_028_1_retry_when_idle_is_a_no_op(reflex_harness: ReflexHarness) -> None:
    """API §4.3: ``retry_run`` is a no-op unless the run ended in error or was cancelled."""
    client = ScriptedClient(HELLO)
    cls = _state_class("RetryIdleState", client)
    await reflex_harness.call("tok", cls, "retry_run")
    assert client.inputs == []


# --- hooks (API §4.4, REQ-020) ---------------------------------------------------------------

custom_seen: list[tuple[str, object]] = []
ends_seen: list[RunStatus] = []


class HookState(AgentState, rx.State):
    agent: ClassVar = ScriptedClient(
        [started(), custom("boom", 0), custom("progress", 1), *text("m1", "ok"), finished()]
    )

    async def on_custom_event(self, name: str, value: Any) -> None:
        if name == "boom":
            raise RuntimeError("handler failed")
        custom_seen.append((name, value))

    async def on_run_end(self, status: RunStatus) -> None:
        ends_seen.append(status)

    def prepare_run_input(self, run_input: RunAgentInput) -> RunAgentInput:
        return run_input.model_copy(update={"forwarded_props": {"tenant": "acme"}})


async def test_REQ_020_custom_events_and_hooks(reflex_harness: ReflexHarness) -> None:
    """REQ-020.1-2, API §4.4: the hooks run; a raising handler does not stop the run."""
    custom_seen.clear()
    ends_seen.clear()
    await reflex_harness.call("tok", HookState, "send_message", text="go")
    state = await reflex_harness.state("tok", HookState)
    assert state.run_status == RunStatus.IDLE
    assert custom_seen == [("progress", 1)]
    assert [r.name for r in state.custom_events] == ["boom", "progress"]
    assert ends_seen == [RunStatus.IDLE]
    agent = HookState.agent
    assert isinstance(agent, ScriptedClient)
    assert agent.inputs[-1].forwarded_props == {"tenant": "acme"}


async def test_API_4_4_create_client_override_is_used(reflex_harness: ReflexHarness) -> None:
    """API §4.4: ``create_client`` is called once per run."""
    made: list[ScriptedClient] = []

    class FactoryState(AgentState, rx.State):
        def create_client(self) -> AgentClient:
            made.append(ScriptedClient(HELLO))
            return made[-1]

    await reflex_harness.call("tok", FactoryState, "send_message", text="one")
    await reflex_harness.call("tok", FactoryState, "send_message", text="two")
    assert len(made) == 2
    assert (await reflex_harness.state("tok", FactoryState)).run_status == RunStatus.IDLE


@client_tool
def pick_day(day: int) -> str:
    """Pick a day."""
    return f"day-{day}"


async def test_REQ_018_2_client_tools_through_agent_state(reflex_harness: ReflexHarness) -> None:
    """REQ-018.1-2: tools are advertised and run; the follow-up run gets the result."""
    first: list[Step] = [started(), *tool_call("c1", "pick_day", '{"day": 2}'), finished()]
    client = ScriptedClient(first, HELLO)
    cls = _state_class("ToolsState", client, client_tools=(pick_day,))
    await reflex_harness.call("tok", cls, "send_message", text="pick")
    state = await reflex_harness.state("tok", cls)
    assert [t.name for t in client.inputs[0].tools] == ["pick_day"]
    assert state.tool_calls[0].result == "day-2"
    assert state.run_status == RunStatus.IDLE
    assert len(client.inputs) == 2


# --- security and isolation (TD §6.1, REQ-003.1) ------------------------------------------


async def test_TD_6_1_forged_drive_run_is_noop(reflex_harness: ReflexHarness) -> None:
    """TD §6.1: ``drive_run`` without a claimed start does nothing."""
    client = ScriptedClient(HELLO)
    cls = _state_class("ForgedDriveState", client)
    await reflex_harness.call("tok", cls, "drive_run")
    await reflex_harness.call("tok", cls, "send_message", text="go")
    await reflex_harness.call("tok", cls, "drive_run")  # a replay after the claim
    assert len(client.inputs) == 1
    assert (await reflex_harness.state("tok", cls)).run_status == RunStatus.IDLE


async def test_REQ_003_1_states_isolated_per_token(reflex_harness: ReflexHarness) -> None:
    """REQ-003.1: each client token has its own conversation."""
    client = ScriptedClient(HELLO)
    cls = _state_class("IsolatedState", client)
    await reflex_harness.call("tok-a", cls, "send_message", text="from a")
    await reflex_harness.call("tok-b", cls, "send_message", text="from b")
    a = await reflex_harness.state("tok-a", cls)
    b = await reflex_harness.state("tok-b", cls)
    assert [m.content for m in a.messages] == ["from a", "hello"]
    assert [m.content for m in b.messages] == ["from b", "hello"]
    assert a.thread_id != b.thread_id
