"""Scripted ``AgentClient`` fakes for the driver tests (T-026…T-028).

A script is a list of steps played by ``stream``:

- an event, or a function of the ``RunAgentInput`` returning one (so events can echo the
  run's IDs, which the driver assigns): see :func:`started`, :func:`finished`;
- ``Sleep(s)``; ``Hang()`` (wait until cancelled); ``Raise(exc)``.

``ScriptedClient(*scripts)`` plays the n-th script on the n-th run (client-tool rounds
start follow-up runs) and records every input, how often a stream was closed and whether
a stream saw ``CancelledError``.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)


@dataclasses.dataclass(frozen=True)
class Sleep:
    seconds: float


@dataclasses.dataclass(frozen=True)
class Hang:
    pass


@dataclasses.dataclass(frozen=True)
class Raise:
    error: BaseException


EventFactory = Callable[[RunAgentInput], BaseEvent]
Step = BaseEvent | EventFactory | Sleep | Hang | Raise


def started() -> EventFactory:
    return lambda ri: RunStartedEvent(thread_id=ri.thread_id, run_id=ri.run_id)


def finished(outcome: dict[str, Any] | None = None) -> EventFactory:
    def build(ri: RunAgentInput) -> BaseEvent:
        data: dict[str, Any] = {"threadId": ri.thread_id, "runId": ri.run_id}
        if outcome is not None:
            data["outcome"] = outcome
        return RunFinishedEvent.model_validate(data)

    return build


def run_error(message: str = "agent failed") -> BaseEvent:
    return RunErrorEvent(message=message)


def text(message_id: str, *deltas: str) -> list[Step]:
    return [
        TextMessageStartEvent(message_id=message_id, role="assistant"),
        *(TextMessageContentEvent(message_id=message_id, delta=d) for d in deltas),
        TextMessageEndEvent(message_id=message_id),
    ]


def tool_call(call_id: str, name: str, args: str, parent: str = "m1") -> list[Step]:
    return [
        ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name, parent_message_id=parent),
        ToolCallArgsEvent(tool_call_id=call_id, delta=args),
        ToolCallEndEvent(tool_call_id=call_id),
    ]


def custom(name: str, value: Any) -> BaseEvent:
    return CustomEvent(name=name, value=value)


class ScriptedClient:
    """An ``AgentClient`` that plays one script per run."""

    def __init__(self, *scripts: Sequence[Step]) -> None:
        self.scripts = [list(s) for s in scripts]
        self.inputs: list[RunAgentInput] = []
        self.closed = 0
        self.cancelled = False
        self.aclosed = 0

    async def stream(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        index = len(self.inputs)
        self.inputs.append(run_input)
        script = self.scripts[min(index, len(self.scripts) - 1)]
        try:
            for step in script:
                if isinstance(step, Sleep):
                    await asyncio.sleep(step.seconds)
                elif isinstance(step, Hang):
                    await asyncio.Event().wait()
                elif isinstance(step, Raise):
                    raise step.error
                elif isinstance(step, BaseEvent):
                    yield step
                else:
                    yield step(run_input)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        finally:
            self.closed += 1

    async def aclose(self) -> None:
        self.aclosed += 1
