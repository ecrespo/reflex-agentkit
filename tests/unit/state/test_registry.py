"""``RunRegistry``: process-local lookup of running drivers (T-025, TD §5.2, DD-004)."""

from __future__ import annotations

import asyncio

import pytest

from reflex_agentkit.state._registry import RunRegistry


async def _forever() -> None:
    await asyncio.Event().wait()


async def test_REQ_007_1_cancel_finds_and_cancels_the_registered_task() -> None:
    """Flow D.1: a hit cancels the driver task right away and returns True."""
    registry = RunRegistry()
    task = asyncio.create_task(_forever())
    registry.register("tok", "run-1", task)
    assert registry.cancel("tok", "run-1") is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


async def test_REQ_007_1_a_miss_returns_false() -> None:
    """Flow D.3: another worker's run (or a finished one) is not found here."""
    registry = RunRegistry()
    task = asyncio.create_task(_forever())
    registry.register("tok", "run-1", task)
    assert registry.cancel("tok", "run-2") is False
    assert registry.cancel("other", "run-1") is False
    assert not task.cancelled()
    task.cancel()


async def test_REQ_007_1_unregister_removes_the_entry_and_is_idempotent() -> None:
    registry = RunRegistry()
    task = asyncio.create_task(_forever())
    registry.register("tok", "run-1", task)
    registry.unregister("tok", "run-1")
    registry.unregister("tok", "run-1")
    assert registry.cancel("tok", "run-1") is False
    assert "tok" not in repr(registry) or len(registry) == 0
    task.cancel()


async def test_REQ_007_1_finished_tasks_are_not_cancelled() -> None:
    registry = RunRegistry()
    task = asyncio.create_task(asyncio.sleep(0))
    await task
    registry.register("tok", "run-1", task)
    assert registry.cancel("tok", "run-1") is False


async def test_REQ_003_1_entries_are_keyed_by_token_and_run() -> None:
    """REQ-003.1: two sessions with the same run id do not collide."""
    registry = RunRegistry()
    a, b = asyncio.create_task(_forever()), asyncio.create_task(_forever())
    registry.register("tok-a", "run", a)
    registry.register("tok-b", "run", b)
    assert len(registry) == 2
    assert registry.cancel("tok-a", "run") is True
    await asyncio.sleep(0)
    assert a.cancelled()
    assert not b.cancelled()
    b.cancel()
