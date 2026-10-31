"""NFR-04: 20 clients streaming at 50 tokens/s on one worker (T-049).

Each fake agent records when it yields a token; the harness records when a delta with
that token reaches the "browser". The lag of a token is the time between the two, with
the default 50 ms flush. Target: no client's lag p95 above 250 ms.
"""

from __future__ import annotations

import asyncio
import re
import statistics
import time
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
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
from reflex_base.utils.format import json_dumps

from reflex_agentkit import AgentState
from reflex_agentkit.core.models import RunStatus

pytestmark = pytest.mark.bench

CLIENTS = 20
TOKENS = 100  # two seconds at 50 tokens/s
TOKEN_INTERVAL_S = 1 / 50
P95_BUDGET_S = 0.250
YIELDED: dict[str, list[float]] = {}


class SteadyAgent:
    """Streams ``TOKENS`` tokens at 50 per second, recording when each is yielded."""

    async def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        session = str(run_input.messages[-1].content)
        times = YIELDED.setdefault(session, [])
        thread_id, run_id = run_input.thread_id, run_input.run_id
        yield RunStartedEvent(thread_id=thread_id, run_id=run_id)
        yield TextMessageStartEvent(message_id=f"m-{session}", role="assistant")
        for i in range(TOKENS):
            await asyncio.sleep(TOKEN_INTERVAL_S)
            times.append(time.monotonic())
            yield TextMessageContentEvent(message_id=f"m-{session}", delta=f"<{session}:{i}>")
        yield TextMessageEndEvent(message_id=f"m-{session}")
        yield RunFinishedEvent(thread_id=thread_id, run_id=run_id)


class SteadyState(AgentState, rx.State):
    agent: ClassVar = SteadyAgent()


def _lags(session: str, harness: ReflexHarness) -> list[float]:
    """The lag of each token: first delta that shows it minus the time it was yielded."""
    yielded = YIELDED[session]
    seen = -1
    lags: list[float] = []
    pattern = re.compile(rf"<{re.escape(session)}:(\d+)>")
    for (token, delta), arrived in zip(harness.deltas, harness.delta_times, strict=True):
        if token != session:
            continue
        indexes = [int(i) for i in pattern.findall(json_dumps(delta))]
        newest = max(indexes, default=-1)
        lags.extend(arrived - yielded[i] for i in range(seen + 1, newest + 1))
        seen = max(seen, newest)
    assert seen == TOKENS - 1, f"{session} saw {seen + 1} of {TOKENS} tokens"
    return lags


async def test_NFR_04_twenty_clients_flush_lag_p95_under_250_ms(
    reflex_harness: ReflexHarness,
) -> None:
    """NFR-04: 20 concurrent clients at 50 tokens/s; every client's lag p95 < 250 ms."""
    YIELDED.clear()
    sessions = [f"c{n:02d}" for n in range(CLIENTS)]
    await asyncio.gather(
        *(reflex_harness.call(s, SteadyState, "send_message", text=s) for s in sessions)
    )
    worst = 0.0
    for session in sessions:
        state = await reflex_harness.state(session, SteadyState)
        assert state.run_status == RunStatus.IDLE
        p95 = statistics.quantiles(_lags(session, reflex_harness), n=100)[94]
        worst = max(worst, p95)
    print(f"\nNFR-04 flush lag: worst client p95 {worst * 1000:.0f} ms over {CLIENTS} clients")
    assert worst < P95_BUDGET_S
