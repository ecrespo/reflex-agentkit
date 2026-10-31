"""The in-process Reflex harness works (T-024, TD §11 OQ-1)."""

from __future__ import annotations

import asyncio

import pytest
import reflex as rx
from helpers.reflex_harness import ReflexHarness


class _HarnessCounter(rx.State):
    count: int = 0
    log: list[str] = []  # noqa: RUF012 - a Reflex var, not a class attribute

    @rx.event
    def bump(self, by: int):  # type: ignore[no-untyped-def]  # returns an EventSpec
        self.count += by
        return _HarnessCounter.grow

    @rx.event(background=True)
    async def grow(self) -> None:
        async with self:
            self.log.append("first")
            self.count += 10
        await asyncio.sleep(0.01)
        async with self:
            self.log.append("second")
            self.count += 100

    @rx.event
    def boom(self) -> None:
        raise RuntimeError("handler failed")

    @rx.event
    def boom_later(self):  # type: ignore[no-untyped-def]  # returns an EventSpec
        return _HarnessCounter.boom_in_background

    @rx.event(background=True)
    async def boom_in_background(self) -> None:
        raise ValueError("background failed")


async def test_OQ_1_foreground_then_background_with_two_lock_sections(
    reflex_harness: ReflexHarness,
) -> None:
    """A foreground handler chains a background one that does ``async with self`` twice."""
    await reflex_harness.call("tok-a", _HarnessCounter, "bump", by=1)
    state = await reflex_harness.state("tok-a", _HarnessCounter)
    assert state.count == 111
    assert state.log == ["first", "second"]
    assert reflex_harness.deltas_for("tok-a")
    assert reflex_harness.errors == []


async def test_OQ_1_tokens_are_isolated(reflex_harness: ReflexHarness) -> None:
    """Each token has its own state instance."""
    await reflex_harness.call("tok-a", _HarnessCounter, "bump", by=1)
    other = await reflex_harness.state("tok-b", _HarnessCounter)
    assert other.count == 0
    assert reflex_harness.deltas_for("tok-b") == []


async def test_OQ_1_handler_exceptions_are_collected(reflex_harness: ReflexHarness) -> None:
    """Exceptions do not vanish into Reflex's logs: ``call`` re-raises them."""
    with pytest.raises(RuntimeError, match="handler failed"):
        await reflex_harness.call("tok-a", _HarnessCounter, "boom")
    with pytest.raises(ValueError, match="background failed"):
        await reflex_harness.call("tok-a", _HarnessCounter, "boom_later")
