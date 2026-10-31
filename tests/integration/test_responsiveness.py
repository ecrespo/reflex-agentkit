"""Responsiveness: a slow agent does not block other sessions (T-031, REQ-024.1)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import ClassVar

import reflex as rx
from ag_ui.core import BaseEvent, RunAgentInput, RunFinishedEvent, RunStartedEvent
from helpers.reflex_harness import ReflexHarness

from reflex_agentkit import AgentState
from reflex_agentkit.core.models import RunStatus

agent_started = asyncio.Event()


class SlowAgent:
    """An agent that does 2 s of blocking work, offloaded to a thread."""

    async def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        yield RunStartedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id)
        agent_started.set()
        await asyncio.to_thread(time.sleep, 2)
        yield RunFinishedEvent(thread_id=run_input.thread_id, run_id=run_input.run_id)


class SlowState(AgentState, rx.State):
    agent: ClassVar = SlowAgent()


async def test_REQ_024_1_other_clients_stay_responsive(reflex_harness: ReflexHarness) -> None:
    """REQ-024.1: while one run works for 2 s, another client's handler takes < 200 ms."""
    agent_started.clear()
    running = await reflex_harness.start("tok-slow", SlowState, "send_message", text="work")
    await asyncio.wait_for(agent_started.wait(), 2)
    began = time.monotonic()
    await reflex_harness.call("tok-fast", SlowState, "set_shared_state", value={"ok": True})
    elapsed = time.monotonic() - began
    assert elapsed < 0.2, f"the handler took {elapsed:.3f} s"
    assert (await reflex_harness.state("tok-fast", SlowState)).shared_state == {"ok": True}
    await asyncio.wait_for(running.wait_all(), 5)
    assert (await reflex_harness.state("tok-slow", SlowState)).run_status == RunStatus.IDLE
