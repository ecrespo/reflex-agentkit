"""``AgentState``: the Reflex state mixin (API §4, TD §3.3, DD-004, DD-006, DD-008).

The conversation lives in one backend-only var, ``_conv``, which Reflex never sends to
the browser. The public vars are a projection of it (DM §7.2), rewritten at every flush.
Configuration is class-level (``ClassVar``) and is never a var (REQ-025.1).
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any, ClassVar

import pydantic
import reflex as rx
from ag_ui.core import RunAgentInput

from reflex_agentkit.core.clients.base import AgentClient, AgentSource, AGUIAgent
from reflex_agentkit.core.clients.in_process import InProcessAGUIClient
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.errors import ConfigurationError, ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    CustomEventRecord,
    PendingInterrupt,
    ReducerConfig,
    RunStatus,
    ToolCall,
    ToolCallStatus,
)
from reflex_agentkit.core.tools import ClientTool
from reflex_agentkit.state._driver import StateView
from reflex_agentkit.state._projection import project, refresh_dirty_args

__all__ = ["AgentState"]

_CONFIG_NAMES = (
    "agent",
    "client_tools",
    "shared_state_model",
    "flush_interval_ms",
    "max_message_length",
    "client_tool_timeout_s",
    "custom_events_limit",
    "max_client_tool_rounds",
)
_CAN_SEND = frozenset({RunStatus.IDLE, RunStatus.CANCELLED, RunStatus.ERROR})


class AgentState(rx.State, mixin=True):
    """Chat with an AG-UI agent from a Reflex app.

    Use it as the first base of your state and set the configuration as ``ClassVar``::

        class ChatState(AgentState, rx.State):
            agent: ClassVar = my_agent

    Without the ``ClassVar`` annotation Reflex would turn the attribute into a state var
    (TD DD-006); ``AgentState`` reports that as a ``ConfigurationError``.
    """

    # --- configuration (API §4.1): class-level, never a var --------------------------------
    agent: ClassVar[AgentSource | None] = None
    client_tools: ClassVar[Sequence[ClientTool]] = ()
    shared_state_model: ClassVar[type[pydantic.BaseModel] | None] = None
    flush_interval_ms: ClassVar[int] = 50
    max_message_length: ClassVar[int] = 32_000
    client_tool_timeout_s: ClassVar[float] = 30.0
    custom_events_limit: ClassVar[int] = 100
    max_client_tool_rounds: ClassVar[int] = 8

    # --- public vars (API §4.2): a projection of _conv ------------------------------------
    messages: list[ChatMessage] = []  # noqa: RUF012 - Reflex copies var defaults
    tool_calls: list[ToolCall] = []  # noqa: RUF012
    pending_interrupt: PendingInterrupt | None = None
    shared_state: dict[str, Any] = {}  # noqa: RUF012
    shared_state_stale: bool = False
    run_status: RunStatus = RunStatus.IDLE
    current_step: str = ""
    thread_id: str = ""
    run_id: str = ""
    error: str = ""
    error_code: ErrorCode | None = None
    custom_events: list[CustomEventRecord] = []  # noqa: RUF012

    # --- backend-only vars (DD-008): never sent to the browser ----------------------------
    _conv: ConversationState | None = None
    _cancel_requested: str = ""
    _pending_start: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # Validated before Reflex binds the class, so a bad class is never registered and
        # an unannotated configuration attribute gets our message, not a VarTypeError.
        # Reflex's metaclass consumes the ``mixin`` keyword and records it in ``_mixin``.
        if not cls.__dict__.get("_mixin", False):
            _validate(cls)
        super().__init_subclass__(**kwargs)

    # --- computed vars (API §4.2) ----------------------------------------------------------
    @rx.var
    def is_running(self) -> bool:
        """Whether a run is streaming."""
        return self.run_status == RunStatus.RUNNING

    @rx.var
    def awaiting_input(self) -> bool:
        """Whether the run is paused on approvals or interrupts."""
        return self.run_status == RunStatus.AWAITING_INPUT

    @rx.var
    def pending_approvals(self) -> list[ToolCall]:
        """The calls waiting for ``approve_tool``/``reject_tool``, in start order."""
        return [c for c in self.tool_calls if c.status == ToolCallStatus.PENDING_APPROVAL]

    @rx.var
    def can_send(self) -> bool:
        """Whether ``send_message`` would start a run."""
        return self.run_status in _CAN_SEND

    # --- hooks (API §4.4) ------------------------------------------------------------------
    def create_client(self) -> AgentClient:
        """The client of one run. The default wraps ``agent``; override for per-session clients."""
        agent = type(self).agent
        if isinstance(agent, AgentClient):
            return agent
        if isinstance(agent, AGUIAgent):
            return InProcessAGUIClient(agent)
        raise ConfigurationError(f"{type(self).__name__}.agent is not set")

    def prepare_run_input(self, run_input: RunAgentInput) -> RunAgentInput:
        """Adjust the input of each run (context, forwarded props, tools). Identity by default."""
        return run_input

    async def on_custom_event(self, name: str, value: Any) -> None:
        """React to a CUSTOM event, under the state lock. No-op by default (REQ-020)."""

    async def on_run_end(self, status: RunStatus) -> None:
        """Called once per run after the final flush. No-op by default."""

    # --- internals -------------------------------------------------------------------------
    @classmethod
    def _reducer_config(cls) -> ReducerConfig:
        return ReducerConfig(
            client_tool_names=frozenset(t.name for t in cls.client_tools),
            custom_events_limit=cls.custom_events_limit,
        )

    def _conversation(self) -> ConversationState:
        """The stored conversation, created on first use."""
        if self._conv is None:
            self._conv = ConversationState.initial(type(self)._reducer_config())
        return self._conv

    def _publish(self, conv: ConversationState) -> None:
        """Store ``conv`` and project it onto the public vars (Flow A.7)."""
        conv = refresh_dirty_args(conv)
        self._conv = conv
        view = project(conv)
        self.messages = view.messages
        self.tool_calls = view.tool_calls
        self.pending_interrupt = view.pending_interrupt
        self.shared_state = view.shared_state
        self.shared_state_stale = view.shared_state_stale
        self.run_status = view.run_status
        self.current_step = view.current_step
        self.thread_id = view.thread_id
        self.run_id = view.run_id
        self.error = view.error
        self.error_code = view.error_code
        self.custom_events = view.custom_events

    def _client_token(self) -> str:
        return str(self.router.session.client_token)

    def _view(self) -> StateView:
        return StateView(
            conv=self._conversation(),
            cancel_requested=self._cancel_requested,
            client_token=self._client_token(),
            publish=self._publish,
        )


class _ReflexStateAccess:
    """The driver's ``StateAccess`` over a background handler's ``async with self``."""

    def __init__(self, state: AgentState) -> None:
        self._state = state

    @asynccontextmanager
    async def locked(self) -> AsyncIterator[StateView]:
        async with self._state:
            yield self._state._view()


# --- configuration checks (API §4.1) --------------------------------------------------------


def _is_class_var(annotation: object) -> bool:
    if isinstance(annotation, str):
        return annotation.split("[", 1)[0].strip() in {"ClassVar", "typing.ClassVar"}
    return annotation is ClassVar or typing.get_origin(annotation) is ClassVar


def _validate(cls: type[AgentState]) -> None:
    """Raise ``ConfigurationError`` naming the attribute (API §4.1, DD-006)."""
    name = cls.__name__
    annotations = inspect.get_annotations(cls)
    for attr in _CONFIG_NAMES:
        if attr in cls.__dict__ and not _is_class_var(annotations.get(attr)):
            raise ConfigurationError(
                f"{name}.{attr} must be annotated as ClassVar "
                f"(`{attr}: ClassVar = ...`), or Reflex makes it a state var"
            )
    overrides_client = cls.create_client is not AgentState.create_client
    agent = cls.agent
    if agent is None:
        if not overrides_client:
            raise ConfigurationError(f"{name}.agent is required unless create_client is overridden")
    elif not isinstance(agent, AgentClient | AGUIAgent):
        raise ConfigurationError(
            f"{name}.agent must be an AgentClient or an AG-UI agent, not {type(agent).__name__}"
        )
    _check_int(name, "flush_interval_ms", cls.flush_interval_ms, minimum=0)
    _check_int(name, "max_message_length", cls.max_message_length, minimum=1)
    _check_int(name, "custom_events_limit", cls.custom_events_limit, minimum=1)
    _check_int(name, "max_client_tool_rounds", cls.max_client_tool_rounds, minimum=1)
    timeout = cls.client_tool_timeout_s
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
        raise ConfigurationError(f"{name}.client_tool_timeout_s must be a number > 0")
    _check_tools(name, cls.client_tools)
    model = cls.shared_state_model
    if model is not None and not (
        isinstance(model, type) and issubclass(model, pydantic.BaseModel)
    ):
        raise ConfigurationError(f"{name}.shared_state_model must be a pydantic.BaseModel subclass")


def _check_int(name: str, attr: str, value: object, *, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigurationError(f"{name}.{attr} must be an int >= {minimum}")


def _check_tools(name: str, tools: object) -> None:
    if isinstance(tools, str | bytes) or not isinstance(tools, Sequence):
        raise ConfigurationError(f"{name}.client_tools must be a sequence of client tools")
    seen: set[str] = set()
    for tool in tools:
        if not isinstance(tool, ClientTool):
            raise ConfigurationError(
                f"{name}.client_tools must hold @client_tool objects, not {type(tool).__name__}"
            )
        if tool.name in seen:
            raise ConfigurationError(f"{name}.client_tools has two tools named {tool.name!r}")
        seen.add(tool.name)
