"""Cancel from another worker through a shared Redis state manager (T-031, REQ-007.6).

Two ``StateManagerRedis`` instances, each with its own event processor, stand in for two
backend workers. The run streams on worker A; ``cancel_run`` is handled by worker B. The
in-process ``RunRegistry`` is disabled, as it would be across processes, so only the
``_cancel_requested`` flag in the shared state can stop the run (TD Flow D.3).

Needs Redis: ``docker run -p 6379:6379 redis:7``, then ``uv run pytest -m redis``.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
import reflex as rx
from helpers.fake_clients import Hang, ScriptedClient, started, text
from helpers.reflex_harness import ReflexHarness
from redis.asyncio import Redis
from reflex.istate.manager.redis import StateManagerRedis

from reflex_agentkit import AgentState
from reflex_agentkit.core.models import RunStatus
from reflex_agentkit.state import _registry

pytestmark = pytest.mark.redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


class RedisCancelState(AgentState, rx.State):
    agent: ClassVar = ScriptedClient([started(), *text("m1", "partial")[:2], Hang()])


@pytest.fixture
async def workers() -> AsyncIterator[tuple[ReflexHarness, ReflexHarness]]:
    # mypy sees StateManagerRedis as abstract (Reflex's overloads); it is concrete.
    managers = [StateManagerRedis(redis=Redis.from_url(REDIS_URL)) for _ in range(2)]  # type: ignore[abstract]
    try:
        async with ReflexHarness(managers[0]) as a, ReflexHarness(managers[1]) as b:
            yield a, b
    finally:
        for manager in managers:
            await manager.close()  # type: ignore[no-untyped-call]


async def test_REQ_007_6_cancel_handled_by_another_worker(
    workers: tuple[ReflexHarness, ReflexHarness], monkeypatch: pytest.MonkeyPatch
) -> None:
    """REQ-007.6: worker B's ``cancel_run`` stops worker A's run in < 1 s."""
    monkeypatch.setattr(_registry.REGISTRY, "cancel", lambda token, run_id: False)
    worker_a, worker_b = workers
    client = RedisCancelState.agent
    assert isinstance(client, ScriptedClient)
    token = f"tok-{uuid.uuid4()}"
    await worker_a.start(token, RedisCancelState, "send_message", text="go")
    deadline = time.monotonic() + 3
    while not (client.inputs and client.inputs[-1].thread_id):
        assert time.monotonic() < deadline, "the run did not start"
        await asyncio.sleep(0.01)
    run_id = client.inputs[-1].run_id
    seen = await worker_b.state(token, RedisCancelState)
    assert (seen.run_status, seen.run_id) == (RunStatus.RUNNING, run_id)

    began = time.monotonic()
    await worker_b.call(token, RedisCancelState, "cancel_run")
    while True:
        state = await worker_b.state(token, RedisCancelState)
        if state.run_status == RunStatus.CANCELLED:
            break
        assert time.monotonic() - began < 1, f"still {state.run_status} after 1 s"
        await asyncio.sleep(0.02)
    assert time.monotonic() - began < 1
    assert state.messages[-1].content == "partial"
    deadline = time.monotonic() + 1
    while not client.cancelled:  # worker A closed the upstream
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)
