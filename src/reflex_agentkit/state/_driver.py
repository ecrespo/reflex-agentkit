"""The run driver and its port to Reflex (TD §3.3 Flows A-E, §5.2).

``StateAccess`` is the driver's only way to touch the Reflex state: ``locked()`` holds
the session's state lock and yields a :class:`StateView` with the stored conversation,
the pending cancel request and a ``publish`` that writes the conversation back and
projects it onto the public vars. ``AgentState`` implements it over ``async with self``;
tests use an in-memory fake, so the driver is tested without Reflex.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import enum
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol

from ag_ui.core import BaseEvent, CustomEvent, RunAgentInput, RunFinishedEvent

from reflex_agentkit.core._log import RunLogger, get_logger
from reflex_agentkit.core.clients.base import AgentClient
from reflex_agentkit.core.commands import (
    apply_cancel,
    apply_client_tool_result,
    apply_failure,
    begin_run,
    request_local_approvals,
    revert_shared_state,
    start_client_tool_round,
)
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import AgentHTTPError, AgentStreamError, ErrorCode
from reflex_agentkit.core.models import (
    CustomEventRecord,
    JsonObject,
    ReducerConfig,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from reflex_agentkit.core.reducer import reduce
from reflex_agentkit.core.run_input import RunInputBuilder
from reflex_agentkit.core.tools import ClientTool
from reflex_agentkit.state._registry import REGISTRY, RunRegistry

__all__ = ["DriverSettings", "RunDriver", "StateAccess", "StateView"]

_logger = get_logger("state.driver")


@dataclasses.dataclass(frozen=True, slots=True)
class StateView:
    """What the driver sees while it holds the state lock.

    Attributes:
        conv: The conversation stored in the session's state.
        cancel_requested: The run ID that ``cancel_run`` asked to stop (``""`` if none).
        client_token: The Reflex client token of the session.
        publish: Store a conversation and project it onto the public vars.
    """

    conv: ConversationState
    cancel_requested: str
    client_token: str
    publish: Callable[[ConversationState], None]


class StateAccess(Protocol):
    """The driver's port to the session state (TD §5.2)."""

    def locked(self) -> AbstractAsyncContextManager[StateView]:
        """Hold the state lock for the duration of the ``async with`` block."""
        ...


# --- the driver --------------------------------------------------------------------------

_END = object()
"""Queue sentinel: the client's stream is exhausted."""

MIN_TICK_S = 0.1
"""A lock section happens at least this often while the upstream is silent (Flow D.3)."""


@dataclasses.dataclass(frozen=True, slots=True)
class _Failure:
    error: BaseException


class _Ownership(enum.Enum):
    """The outcome of a lock section (Flow A.7, D.3)."""

    KEPT = "kept"
    LOST = "lost"
    CANCELLED = "cancelled"


SHUTDOWN_MESSAGE = "the run was interrupted: the server is shutting down"


@dataclasses.dataclass(frozen=True, slots=True)
class DriverSettings:
    """The ``AgentState`` configuration the driver needs (API §4.1)."""

    reducer_config: ReducerConfig
    flush_interval_ms: int = 50
    client_tools: Sequence[ClientTool] = ()
    client_tool_timeout_s: float = 30.0
    max_client_tool_rounds: int = 8
    queue_size: int = 1024
    validate_shared_state: Callable[[JsonObject], bool] | None = None
    """Checks every shared-state value the agent sends (``shared_state_model``, REQ-016.5)."""


CustomHook = Callable[[list[CustomEventRecord]], Awaitable[None]]
RunEndHook = Callable[[RunStatus], Awaitable[None]]
InputHook = Callable[[RunAgentInput], RunAgentInput]


def _failure(conv: ConversationState, error: BaseException, log: RunLogger) -> ConversationState:
    """Map a stream failure onto the conversation (TD Flow E).

    Only the exception type is logged above DEBUG: agent errors may quote user content
    (REQ-027.2). The traceback is logged at DEBUG.
    """
    if isinstance(error, AgentHTTPError):
        code, message = ErrorCode.AGENT_HTTP_ERROR, str(error)
    elif isinstance(error, AgentStreamError) and error.reason != "agent_raised":
        code, message = ErrorCode.AGENT_STREAM_ERROR, str(error)
    elif isinstance(error, AgentStreamError):
        code, message = ErrorCode.AGENT_EXCEPTION, str(error)
    else:
        code = ErrorCode.AGENT_EXCEPTION
        message = f"the agent client raised {type(error).__name__}"
    cause = error.__cause__ or error
    log.error("run failed: %s (%s)", code.value, type(cause).__name__)
    log.debug("run failure traceback", exc_info=error)
    return apply_failure(conv, code, message)


class RunDriver:
    """Streams one turn of a conversation into the session state (TD Flows A, B, D, E).

    It owns its run: it reduces events into a local conversation, publishes it at most
    once per flush interval under the state lock, and stops silently when the stored
    conversation no longer belongs to its run (REQ-026.2). Nothing escapes :meth:`run`.

    Args:
        access: The port to the session state.
        client_factory: ``create_client()``; called once per run.
        settings: Batching, client tools and limits.
        prepare_input: ``prepare_run_input()``.
        on_flush: Receives the CUSTOM events since the previous flush, under the lock.
        on_run_end: Receives the final status, once, after the final flush.
        registry: Where the driver task is registered for same-worker cancels.
        client_token: The session's Reflex token (the registry key).
    """

    def __init__(
        self,
        access: StateAccess,
        *,
        client_factory: Callable[[], AgentClient],
        settings: DriverSettings,
        prepare_input: InputHook | None = None,
        on_flush: CustomHook | None = None,
        on_run_end: RunEndHook | None = None,
        registry: RunRegistry = REGISTRY,
        client_token: str = "",
    ) -> None:
        self._access = access
        self._client_factory = client_factory
        self._settings = settings
        self._prepare_input = prepare_input
        self._on_flush = on_flush
        self._on_run_end = on_run_end
        self._registry = registry
        self._token = client_token
        self._builder = RunInputBuilder(client_tools=tuple(settings.client_tools))
        self._tools = {tool.name: tool for tool in settings.client_tools}
        self._rounds = 0
        self._run_id = ""
        self._conv: ConversationState | None = None
        self._log = RunLogger(_logger, thread_id="", run_id="")
        self._events = 0
        self._flushes = 0

    async def run(self, conv: ConversationState) -> None:
        """Drive the run that ``begin_run`` started on ``conv`` until it ends."""
        started = time.monotonic()
        self._enter_run(conv)
        self._conv = conv
        final: ConversationState | None = None
        try:
            final = await self._turn(conv)
        except asyncio.CancelledError:
            # Flow D.2: the registry path (or a worker shutdown). The driver owns its task
            # and nothing awaits it, so the cancellation is absorbed, not re-raised.
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()
            final = await self._after_cancel()
        finally:
            self._registry.unregister(self._token, self._run_id)
        status = "ownership lost" if final is None else final.run_status.value
        self._log.info(
            "run ended: status=%s events=%d flushes=%d client_tool_rounds=%d duration=%.3fs",
            status,
            self._events,
            self._flushes,
            self._rounds,
            time.monotonic() - started,
        )
        if final is not None:
            await self._run_end_hook(final.run_status)

    async def _turn(self, conv: ConversationState) -> ConversationState | None:
        """Runs and client-tool rounds until the turn ends (Flow A.8, B, C.4).

        A conversation that starts with running client-tool calls (approved locally,
        Flow C.4) runs their handlers before the first stream.
        """
        current: ConversationState | None = conv
        while current is not None and current.run_status is RunStatus.RUNNING:
            if self._awaiting_client_tools(current):
                current = await self._client_round(current)
                if current is None or current.run_status is not RunStatus.RUNNING:
                    return current
                current = await self._follow_up(current)
                if current is None or current.run_status is not RunStatus.RUNNING:
                    return current
            current = await self._stream(current)
            if (
                current is not None
                and current.run_status is RunStatus.RUNNING
                and not self._awaiting_client_tools(current)
            ):
                # RUN_FINISHED listed pending calls that are not runnable client tools.
                self._log.warning("run finished with pending calls that cannot run here")
                return await self._final_flush(current.with_(run_status=RunStatus.IDLE), [])
        return current

    @staticmethod
    def _awaiting_client_tools(conv: ConversationState) -> bool:
        return any(c.is_client_tool and c.status is ToolCallStatus.RUNNING for c in conv.tool_calls)

    async def _client_round(self, conv: ConversationState) -> ConversationState | None:
        """Flow B.1-4: run the handlers outside the lock, record results, flush."""
        running = [
            c for c in conv.tool_calls if c.is_client_tool and c.status is ToolCallStatus.RUNNING
        ]
        to_approve = [c.id for c in running if self._needs_approval(c)]
        ready = [c for c in running if c.id not in to_approve]
        if ready:
            conv = start_client_tool_round(conv, max_rounds=self._settings.max_client_tool_rounds)
            if conv.run_status is not RunStatus.RUNNING:
                self._log.error("run failed: %s", ErrorCode.CLIENT_TOOL_LOOP_LIMIT.value)
                return await self._final_flush(conv, [])
            self._rounds += 1
            self._conv = conv
            self._log.info("client-tool round %d: %d call(s)", conv.client_tool_rounds, len(ready))
            results = await self._run_handlers(ready)
            if not isinstance(results, list):
                return results  # cancelled (flag path) or ownership lost meanwhile
            for call, (ok, text) in zip(ready, results, strict=True):
                conv = apply_client_tool_result(conv, call.id, text, is_error=not ok)
        if to_approve:
            conv = request_local_approvals(conv, to_approve)
            self._log.info("waiting for %d local approval(s)", len(to_approve))
        return await self._final_flush(conv, [])

    def _needs_approval(self, call: ToolCall) -> bool:
        """Approval-required and not yet approved (an approved call has a local interrupt)."""
        tool = self._tools.get(call.name)
        return tool is not None and tool.requires_approval and call.interrupt_id is None

    async def _run_handlers(
        self, calls: list[ToolCall]
    ) -> list[tuple[bool, str]] | ConversationState | None:
        """Run the handlers concurrently; keep checking ownership and cancels (Flow D.3)."""
        gathered = asyncio.gather(*(self._invoke(c) for c in calls))
        tick = max(self._settings.flush_interval_ms / 1000, MIN_TICK_S)
        try:
            while True:
                done, _ = await asyncio.wait({gathered}, timeout=tick)
                if done:
                    return gathered.result()
                assert self._conv is not None  # noqa: S101 - set by _client_round
                outcome = await self._flush(self._conv, [], publish=False)
                if outcome is not _Ownership.KEPT:
                    return self._stopped(outcome)
        finally:
            if not gathered.done():
                gathered.cancel()
                await asyncio.wait({gathered})

    async def _invoke(self, call: ToolCall) -> tuple[bool, str]:
        tool = self._tools.get(call.name)
        if tool is None:
            return False, f"The client tool {call.name!r} is not registered."
        if call.args is None:
            return False, "The tool arguments are not valid JSON."
        timeout = tool.timeout_s
        if timeout is None:
            timeout = self._settings.client_tool_timeout_s
        try:
            ok, text = await tool.invoke(dict(call.args), timeout)
        except Exception as exc:  # invoke() returns failures; this is a last resort
            ok, text = False, f"{type(exc).__name__}: {exc}"
        if not ok:
            # The text may quote arguments or handler data: only the name above DEBUG.
            self._log.warning("client tool %s failed", call.name)
            self._log.debug("client tool %s failed: %s", call.name, text)
        return ok, text

    async def _follow_up(self, conv: ConversationState) -> ConversationState | None:
        """Flow B.5: start the follow-up run in this task, with a new ``run_id``."""
        follow_up = begin_run(conv, config=conv.config, resume=False)
        outcome = await self._flush(follow_up, [], publish=True)  # checked against the old run
        if outcome is not _Ownership.KEPT:
            return self._stopped(outcome)
        self._enter_run(follow_up)
        self._conv = follow_up
        self._log.info("follow-up run started")
        return follow_up

    def _enter_run(self, conv: ConversationState) -> None:
        if self._run_id:
            self._registry.unregister(self._token, self._run_id)
        self._run_id = conv.run_id
        self._log = RunLogger(_logger, thread_id=conv.thread_id, run_id=conv.run_id)
        task = asyncio.current_task()
        if task is not None:
            self._registry.register(self._token, conv.run_id, task)

    async def _stream(self, conv: ConversationState) -> ConversationState | None:
        """One run: start the pump, consume until the end, close the upstream."""
        try:
            client = self._client_factory()
            run_input = self._builder.build(conv)
            if self._prepare_input is not None:
                run_input = self._prepare_input(run_input)
        except Exception as exc:
            self._log.error("could not start the run: %s", type(exc).__name__)
            self._log.debug("start failure traceback", exc_info=exc)
            message = f"the agent client could not be created ({type(exc).__name__})"
            failed = apply_failure(conv, ErrorCode.AGENT_EXCEPTION, message)
            return await self._final_flush(failed, [])
        queue: asyncio.Queue[object] = asyncio.Queue(maxsize=self._settings.queue_size)
        pump = asyncio.create_task(self._pump(client, run_input, queue))
        try:
            return await self._consume(conv, queue)
        finally:
            pump.cancel()
            await asyncio.wait({pump})

    async def _pump(
        self, client: AgentClient, run_input: RunAgentInput, queue: asyncio.Queue[object]
    ) -> None:
        """Forward the client's events into the bounded queue (DD-003)."""
        stream = client.stream(run_input)
        try:
            async for event in stream:
                await queue.put(event)
            await queue.put(_END)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await queue.put(_Failure(exc))
        finally:
            closer = getattr(stream, "aclose", None)
            if closer is not None:
                with contextlib.suppress(Exception):
                    await closer()

    async def _consume(
        self, conv: ConversationState, queue: asyncio.Queue[object]
    ) -> ConversationState | None:
        """Reduce events; flush on deadline, on terminal events and on silent ticks."""
        interval = self._settings.flush_interval_ms / 1000
        tick = max(interval, MIN_TICK_S)
        dirty = False
        deadline = 0.0
        last_lock = time.monotonic()
        custom: list[CustomEventRecord] = []
        while True:
            wait = (deadline if dirty else last_lock + tick) - time.monotonic()
            try:
                item = await asyncio.wait_for(queue.get(), max(wait, 0.0))
            except TimeoutError:
                outcome = await self._flush(conv, custom, publish=dirty)
                if outcome is not _Ownership.KEPT:
                    return self._stopped(outcome)
                dirty, custom, last_lock = False, [], time.monotonic()
                continue
            if item is _END:
                message = "the agent's event stream ended unexpectedly"
                failed = apply_failure(conv, ErrorCode.AGENT_STREAM_ERROR, message)
                self._log.error("run failed: %s (no terminal event)", failed.error_code)
                return await self._final_flush(failed, custom)
            if isinstance(item, _Failure):
                return await self._final_flush(_failure(conv, item.error, self._log), custom)
            assert isinstance(item, BaseEvent)  # noqa: S101 - the pump only queues events
            conv = self._apply(conv, item, custom)
            if self._is_terminal(conv, item):
                return await self._final_flush(conv, custom)
            now = time.monotonic()
            if not dirty:
                dirty, deadline = True, now + interval
            if now >= deadline:
                outcome = await self._flush(conv, custom, publish=True)
                if outcome is not _Ownership.KEPT:
                    return self._stopped(outcome)
                dirty, custom, last_lock = False, [], time.monotonic()

    def _apply(
        self, conv: ConversationState, event: BaseEvent, custom: list[CustomEventRecord]
    ) -> ConversationState:
        """Reduce one event; log and drop its diagnostics; collect CUSTOM events."""
        self._events += 1
        self._log.debug("event %s", event.type.value)
        running = conv.run_status is RunStatus.RUNNING
        previous_state = conv.shared_state
        conv = reduce(conv, event)
        validate = self._settings.validate_shared_state
        if (
            validate is not None
            and conv.shared_state is not previous_state
            and not validate(conv.shared_state)
        ):
            conv = revert_shared_state(conv, previous_state)
        if isinstance(event, CustomEvent) and running:
            custom.append(CustomEventRecord(name=event.name, value=event.value, run_id=conv.run_id))
        if conv.diagnostics:
            for diagnostic in conv.diagnostics:
                # A message may quote content (a failed patch quotes shared-state values),
                # so above DEBUG only the code and the event type are logged (REQ-027.2).
                if diagnostic.level != "debug":
                    self._log.warning(
                        "reducer diagnostic %s on %s",
                        diagnostic.code.value,
                        diagnostic.event_type or "an event",
                    )
                self._log.debug("%s (%s)", diagnostic.message, diagnostic.code.value)
            conv = conv.with_(diagnostics=())
        self._conv = conv
        return conv

    def _is_terminal(self, conv: ConversationState, event: BaseEvent) -> bool:
        if conv.run_status is not RunStatus.RUNNING:
            return True
        return isinstance(event, RunFinishedEvent) and event.run_id == self._run_id

    async def _final_flush(
        self, conv: ConversationState, custom: list[CustomEventRecord]
    ) -> ConversationState | None:
        self._conv = conv
        outcome = await self._flush(conv, custom, publish=True)
        return conv if outcome is _Ownership.KEPT else self._stopped(outcome)

    def _stopped(self, outcome: _Ownership) -> ConversationState | None:
        """The final conversation after a lock section stopped the run."""
        return self._conv if outcome is _Ownership.CANCELLED else None

    async def _after_cancel(self) -> ConversationState | None:
        """The final lock section after the task was cancelled (Flow D.2, Flow E)."""
        conv = self._conv
        if conv is None:  # pragma: no cover - run() sets it before anything can cancel
            return None
        async with self._access.locked() as view:
            if view.conv.run_id != self._run_id:
                self._log.info("cancelled after ownership was lost")
                return None
            if view.cancel_requested == self._run_id:
                self._log.info("run cancelled")
                final = apply_cancel(conv)
            else:
                self._log.warning("run interrupted by a worker shutdown")
                final = apply_failure(conv, ErrorCode.AGENT_STREAM_ERROR, SHUTDOWN_MESSAGE)
            view.publish(final)
            self._flushes += 1
        return final

    async def _flush(
        self, conv: ConversationState, custom: list[CustomEventRecord], *, publish: bool
    ) -> _Ownership:
        """One lock section: the ownership check, then publish and hooks (Flow A.7)."""
        async with self._access.locked() as view:
            if view.conv.run_id != self._run_id:
                self._log.info("ownership lost: the stored conversation changed")
                return _Ownership.LOST
            if view.cancel_requested == self._run_id:
                # Flow D.3: a cancel from another worker; queued events are discarded.
                self._log.info("run cancelled")
                self._conv = apply_cancel(conv)
                view.publish(self._conv)
                self._flushes += 1
                return _Ownership.CANCELLED
            if publish:
                view.publish(conv)
                self._flushes += 1
                if custom and self._on_flush is not None:
                    try:
                        await self._on_flush(list(custom))
                    except Exception as exc:
                        self._log.warning("on_custom_event raised %s", type(exc).__name__)
                        self._log.debug("on_custom_event traceback", exc_info=exc)
        return _Ownership.KEPT

    async def _run_end_hook(self, status: RunStatus) -> None:
        if self._on_run_end is None:
            return
        try:
            await self._on_run_end(status)
        except Exception as exc:
            self._log.warning("on_run_end raised %s", type(exc).__name__)
            self._log.debug("on_run_end traceback", exc_info=exc)
