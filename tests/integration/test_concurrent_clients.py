"""Two clients streaming at once stay isolated (T-031, REQ-003.2)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import ClassVar

import reflex as rx
from ag_ui.core import (
    BaseEvent,
    RunAgentInput,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)
from helpers.reflex_harness import ReflexHarness

from reflex_agentkit import AgentState


class EchoAgent:
    """Echoes the last user message word by word, yielding to the loop between words."""

    async def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        thread_id, run_id = run_input.thread_id, run_input.run_id
        yield RunStartedEvent(thread_id=thread_id, run_id=run_id)
        text = str(run_input.messages[-1].content)
        message_id = f"echo-{run_input.run_id}"
        yield TextMessageStartEvent(message_id=message_id, role="assistant")
        for word in text.split():
            await asyncio.sleep(0.01)
            yield TextMessageContentEvent(message_id=message_id, delta=f"{word} ")
        yield TextMessageEndEvent(message_id=message_id)
        yield RunFinishedEvent(thread_id=thread_id, run_id=run_id)


class EchoState(AgentState, rx.State):
    agent: ClassVar = EchoAgent()
    flush_interval_ms: ClassVar = 0


async def test_REQ_003_2_concurrent_clients_isolated(reflex_harness: ReflexHarness) -> None:
    """REQ-003.2: each client receives only its own run's messages."""
    texts = {"tok-a": "alpha " * 20, "tok-b": "beta " * 20}
    await asyncio.gather(
        *(
            reflex_harness.call(session, EchoState, "send_message", text=text)
            for session, text in texts.items()
        )
    )
    for session, text in texts.items():
        state = await reflex_harness.state(session, EchoState)
        assert [m.content for m in state.messages] == [text.strip(), text]
        other = "beta" if session == "tok-a" else "alpha"
        assert all(other not in str(delta) for delta in reflex_harness.deltas_for(session))
