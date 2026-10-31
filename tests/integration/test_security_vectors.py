"""TD §6.1 attack surface, one test per vector, through Reflex's event processor (T-049).

Every public ``AgentState`` event handler can be called from the browser with any
arguments, so each vector is driven the way a forged client would drive it.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import pytest
import reflex as rx
from helpers.fake_clients import ScriptedClient, Step, finished, started, text, tool_call
from helpers.fake_server import FakeServer, raw, status
from helpers.reflex_harness import ReflexHarness
from helpers.ui_state import render
from reflex_base.registry import RegistrationContext
from reflex_base.utils.format import json_dumps

from reflex_agentkit import AgentState, HttpAGUIClient, agent_chat
from reflex_agentkit.core.commands import MAX_PATCH_OPS, MAX_PAYLOAD_BYTES
from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import RunStatus, ToolCallStatus

SECRET = "SECRET-SV-42"  # noqa: S105 - the canary value the tests look for
HELLO: list[Step] = [started(), *text("m1", "hello"), finished()]
APPROVAL_PAUSE: list[Step] = [
    started(),
    *tool_call("c1", "book", '{"city": "Lisbon"}'),
    finished(
        {
            "type": "interrupt",
            "interrupts": [{"id": "int-c1", "reason": "tool_call", "toolCallId": "c1"}],
        }
    ),
]
QUESTION_PAUSE: list[Step] = [
    started(),
    finished({"type": "interrupt", "interrupts": [{"id": "i1", "reason": "ask"}]}),
]
OVERSIZED = "x" * (MAX_PAYLOAD_BYTES + 1)


def _state_class(name: str, client: Any) -> type[AgentState]:
    namespace = {"__annotations__": {"agent": "ClassVar"}, "agent": client, "__module__": __name__}
    return type(name, (AgentState, rx.State), namespace)


# --- forged triggers ----------------------------------------------------------------------


async def test_TD_6_1_forged_drive_run_from_another_session_starts_nothing(
    reflex_harness: ReflexHarness,
) -> None:
    """A ``drive_run`` sent by a session with no scheduled run is a no-op, every time."""
    client = ScriptedClient(HELLO)
    cls = _state_class("SvForgedDrive", client)
    await reflex_harness.call("victim", cls, "send_message", text="hi")
    for _ in range(3):
        await reflex_harness.call("attacker", cls, "drive_run")
        await reflex_harness.call("victim", cls, "drive_run")
    assert len(client.inputs) == 1
    attacker = await reflex_harness.state("attacker", cls)
    assert (attacker.messages, attacker.run_status) == ([], RunStatus.IDLE)


async def test_TD_6_1_forged_argument_types_are_ignored(reflex_harness: ReflexHarness) -> None:
    """Handlers check their argument types before touching the conversation."""
    client = ScriptedClient(APPROVAL_PAUSE, HELLO)
    cls = _state_class("SvForgedTypes", client)
    await reflex_harness.call("tok", cls, "send_message", text={"not": "text"})
    assert client.inputs == []
    await reflex_harness.call("tok", cls, "send_message", text="book")
    await reflex_harness.call("tok", cls, "approve_tool", call_id={"$ne": ""})
    await reflex_harness.call("tok", cls, "approve_tool", call_id="c1", edited_args=["a"])
    await reflex_harness.call("tok", cls, "reject_tool", call_id="c1", reason=["no"])
    state = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.AWAITING_INPUT
    assert state.tool_calls[0].status == ToolCallStatus.PENDING_APPROVAL
    assert len(client.inputs) == 1


# --- oversized payloads -------------------------------------------------------------------


async def test_TD_6_1_oversized_edited_args_keep_the_call_pending(
    reflex_harness: ReflexHarness,
) -> None:
    """Edited arguments above 64 KiB serialized set ``INVALID_EDITED_ARGS``."""
    client = ScriptedClient(APPROVAL_PAUSE, HELLO)
    cls = _state_class("SvBigEdit", client)
    await reflex_harness.call("tok", cls, "send_message", text="book")
    await reflex_harness.call(
        "tok", cls, "approve_tool", call_id="c1", edited_args={"x": OVERSIZED}
    )
    state = await reflex_harness.state("tok", cls)
    assert state.error_code == ErrorCode.INVALID_EDITED_ARGS
    assert str(MAX_PAYLOAD_BYTES) in state.error
    assert state.tool_calls[0].status == ToolCallStatus.PENDING_APPROVAL
    assert len(client.inputs) == 1


async def test_TD_6_1_oversized_rejection_reason_is_ignored(reflex_harness: ReflexHarness) -> None:
    """A rejection reason above the cap changes nothing; the call stays pending."""
    client = ScriptedClient(APPROVAL_PAUSE, HELLO)
    cls = _state_class("SvBigReason", client)
    await reflex_harness.call("tok", cls, "send_message", text="book")
    await reflex_harness.call("tok", cls, "reject_tool", call_id="c1", reason=OVERSIZED)
    state = await reflex_harness.state("tok", cls)
    assert state.tool_calls[0].status == ToolCallStatus.PENDING_APPROVAL
    assert len(client.inputs) == 1


async def test_TD_6_1_oversized_interrupt_response_is_ignored(
    reflex_harness: ReflexHarness,
) -> None:
    """An interrupt answer above the cap (as text or as JSON) does not resume the run."""
    client = ScriptedClient(QUESTION_PAUSE, HELLO)
    cls = _state_class("SvBigAnswer", client)
    await reflex_harness.call("tok", cls, "send_message", text="ask me")
    await reflex_harness.call("tok", cls, "respond_to_interrupt", payload=OVERSIZED)
    await reflex_harness.call("tok", cls, "respond_to_interrupt", payload={"a": OVERSIZED})
    state = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.AWAITING_INPUT
    assert state.pending_interrupt is not None
    assert len(client.inputs) == 1
    await reflex_harness.call("tok", cls, "respond_to_interrupt", payload="fine")
    assert len(client.inputs) == 2


async def test_TD_6_1_oversized_or_amplifying_shared_state_is_rejected(
    reflex_harness: ReflexHarness,
) -> None:
    """Shared-state writes and patches are capped, including ``copy`` amplification."""
    cls = _state_class("SvBigShared", ScriptedClient(HELLO))
    await reflex_harness.call("tok", cls, "set_shared_state", value={"seed": "y" * 1000})
    await reflex_harness.call("tok", cls, "set_shared_state", value={"x": OVERSIZED})
    state = await reflex_harness.state("tok", cls)
    assert state.error_code == ErrorCode.SHARED_STATE_INVALID
    assert state.shared_state == {"seed": "y" * 1000}

    doubling = [{"op": "copy", "from": "", "path": f"/k{i}"} for i in range(40)]
    await reflex_harness.call("tok", cls, "patch_shared_state", ops=doubling)
    too_many = [{"op": "add", "path": f"/k{i}", "value": i} for i in range(MAX_PATCH_OPS + 1)]
    await reflex_harness.call("tok", cls, "patch_shared_state", ops=too_many)
    state = await reflex_harness.state("tok", cls)
    assert state.error_code == ErrorCode.SHARED_STATE_PATCH_FAILED
    assert state.shared_state == {"seed": "y" * 1000}


# --- cross-session actions ----------------------------------------------------------------


async def test_TD_6_1_another_session_cannot_answer_a_pending_call(
    reflex_harness: ReflexHarness,
) -> None:
    """Call and interrupt IDs resolve only in the caller's own conversation (REQ-003)."""
    client = ScriptedClient(APPROVAL_PAUSE, HELLO)
    cls = _state_class("SvCrossSession", client)
    await reflex_harness.call("victim", cls, "send_message", text="book")
    await reflex_harness.call("attacker", cls, "approve_tool", call_id="c1")
    await reflex_harness.call("attacker", cls, "reject_tool", call_id="c1", reason="no")
    await reflex_harness.call("attacker", cls, "respond_to_interrupt", payload="yes")
    await reflex_harness.call("attacker", cls, "cancel_run")
    victim = await reflex_harness.state("victim", cls)
    assert victim.run_status == RunStatus.AWAITING_INPUT
    assert victim.tool_calls[0].status == ToolCallStatus.PENDING_APPROVAL
    assert len(client.inputs) == 1


# --- agent output in the browser (XSS) ----------------------------------------------------


async def test_TD_6_1_agent_html_is_kept_as_data_and_never_rendered_raw(
    reflex_harness: ReflexHarness,
) -> None:
    """DD-015: markup from the agent stays text; the chat has no raw-HTML path."""
    payload = '<script>alert(1)</script><img src=x onerror="alert(2)">'
    script: list[Step] = [
        started(),
        *text("m1", payload),
        *tool_call("c1", "show", '{"html": "<script>alert(3)</script>"}'),
        finished(),
    ]
    cls = _state_class("SvXss", ScriptedClient(script))
    await reflex_harness.call("tok", cls, "send_message", text="hi")
    state = await reflex_harness.state("tok", cls)
    assert state.messages[-1].content == payload  # stored verbatim, as data
    compiled = render(agent_chat(cls))
    for raw_html_path in ("dangerouslySetInnerHTML", "rehypeRaw", "rehype-raw", "innerHTML"):
        assert raw_html_path not in compiled


# --- secrets and the agent endpoint -------------------------------------------------------


async def test_TD_6_2_an_echoed_header_never_reaches_the_state_or_the_logs(
    fake_agui_server: Any, reflex_harness: ReflexHarness, caplog: pytest.LogCaptureFixture
) -> None:
    """A failing server that echoes the header: no state var, delta or log record holds it."""
    server: FakeServer = fake_agui_server([status(401), raw(f"bad token Bearer {SECRET}")])
    client = HttpAGUIClient(server.url, headers={"Authorization": f"Bearer {SECRET}"})
    cls = _state_class("SvEchoedHeader", client)
    try:
        with caplog.at_level(logging.DEBUG):
            await reflex_harness.call("tok", cls, "send_message", text="hello")
    finally:
        await client.aclose()
    state = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.ERROR
    assert SECRET not in state.error
    assert SECRET not in json_dumps(state.dict())
    assert all(SECRET not in json_dumps(d) for d in reflex_harness.deltas_for("tok"))
    # The body excerpt is content: it may appear at DEBUG (REQ-027.2), never above it.
    assert all(SECRET not in r.getMessage() for r in caplog.records if r.levelno > logging.DEBUG)


HOOKS = {"create_client", "prepare_run_input", "on_custom_event", "on_run_end"}
NOT_HANDLERS = {*HOOKS, "typed_shared_state"}


def test_TD_6_1_hooks_are_not_browser_callable_even_when_overridden() -> None:
    """Reflex registers public methods as handlers; the hooks and overrides are excluded."""
    calls: list[str] = []

    class SvHooks(AgentState, rx.State):
        agent: ClassVar = HttpAGUIClient("http://agent.internal")

        async def on_run_end(self, status: RunStatus) -> None:
            calls.append("persisted")  # an app side effect the browser must not reach

        def prepare_run_input(self, run_input: Any) -> Any:
            return run_input

        @rx.event
        def my_event(self) -> None:
            """An app handler stays a handler."""

    assert not NOT_HANDLERS & set(SvHooks.event_handlers)
    assert {"send_message", "drive_run", "my_event"} <= set(SvHooks.event_handlers)
    assert not NOT_HANDLERS & set(AgentState.event_handlers)
    assert callable(SvHooks.on_run_end)
    assert calls == []


async def test_TD_6_1_a_forged_hook_event_is_rejected(reflex_harness: ReflexHarness) -> None:
    """An event naming a hook does not run it."""
    calls: list[str] = []

    async def on_run_end(self: Any, status: RunStatus) -> None:
        calls.append(str(status))

    namespace = {
        "__annotations__": {"agent": "ClassVar"},
        "agent": ScriptedClient(HELLO),
        "__module__": __name__,
        "on_run_end": on_run_end,
    }
    cls: type[AgentState] = type("SvForgedHook", (AgentState, rx.State), namespace)
    # The processor resolves an event name through this registry; a miss is a KeyError.
    registered = RegistrationContext.get().event_handlers
    assert f"{cls.get_full_name()}.send_message" in registered
    assert f"{cls.get_full_name()}.on_run_end" not in registered
    await reflex_harness.call("tok", cls, "send_message", text="hi")
    assert calls == ["idle"]  # the real run still calls the hook


def test_TD_6_1_the_browser_cannot_configure_the_agent_endpoint() -> None:
    """SSRF: no event handler takes a URL or headers, and ``agent`` is not a state var."""

    class SvEndpoint(AgentState, rx.State):
        agent: ClassVar = HttpAGUIClient("http://agent.internal")

    for name, handler in SvEndpoint.event_handlers.items():
        params = handler.fn.__code__.co_varnames[: handler.fn.__code__.co_argcount]
        assert not {"url", "headers", "endpoint", "agent", "client"} & set(params), name
    assert "agent" not in SvEndpoint.vars
    assert "http://agent.internal" not in json_dumps(SvEndpoint().dict())


def test_TD_6_1_hooks_from_another_mixin_are_not_browser_callable() -> None:
    """An override inherited from a Reflex mixin that is not an ``AgentState`` is hidden too."""

    class SvHookMixin(rx.State, mixin=True):
        async def on_run_end(self, status: RunStatus) -> None:
            pass

        def create_client(self) -> Any:
            return HttpAGUIClient("http://agent.internal")

    class SvMixedHooks(SvHookMixin, AgentState, rx.State):
        agent: ClassVar = HttpAGUIClient("http://agent.internal")

    assert not NOT_HANDLERS & set(SvMixedHooks.event_handlers)
    assert "send_message" in SvMixedHooks.event_handlers


def test_TD_6_1_a_hook_decorated_as_an_event_stays_hidden() -> None:
    """``@rx.event`` returns the plain function, so the flag still keeps the hook hidden."""

    class SvEventHook(AgentState, rx.State):
        agent: ClassVar = HttpAGUIClient("http://agent.internal")

        @rx.event
        async def on_run_end(self, status: RunStatus) -> None:  # type: ignore[override]
            pass

    assert "on_run_end" not in SvEventHook.event_handlers
