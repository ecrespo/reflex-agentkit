"""Value types, enums and JSON aliases of the pure core (DM §2, §3, §6, §8; API §5).

Every value type is a frozen, slotted dataclass (R-1) whose collections are tuples (R-2)
and whose enums are ``StrEnum`` (R-3), so the same types serve as Reflex var types (R-5).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, TypeAlias, Union, cast

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

__all__ = [
    "ChatMessage",
    "CustomEventRecord",
    "Diagnostic",
    "DiagnosticCode",
    "DiagnosticLevel",
    "InterruptAnswer",
    "JsonObject",
    "JsonValue",
    "MessageRole",
    "OpenInterrupt",
    "PendingInterrupt",
    "ReasoningRecord",
    "ReducerConfig",
    "ResumeStatus",
    "RunStatus",
    "TolerantPickle",
    "ToolCall",
    "ToolCallStatus",
]

# DM R-4. ``Union`` (not ``|``) because the alias is recursive and must stay a runtime value.
JsonValue: TypeAlias = Union[  # noqa: UP007
    bool, int, float, str, list["JsonValue"], dict[str, "JsonValue"], None
]
JsonObject: TypeAlias = dict[str, JsonValue]

DiagnosticLevel: TypeAlias = Literal["debug", "warning"]
ResumeStatus: TypeAlias = Literal["resolved", "cancelled"]


class MessageRole(StrEnum):
    """AG-UI message roles (DM §6). Only user/assistant/tool are projected (DM §3.1)."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"
    DEVELOPER = "developer"


class RunStatus(StrEnum):
    """Run status state machine values (API §4.5)."""

    IDLE = "idle"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    CANCELLED = "cancelled"
    ERROR = "error"


class ToolCallStatus(StrEnum):
    """Tool call status state machine values (API §4.6)."""

    STREAMING = "streaming"
    PENDING_APPROVAL = "pending_approval"
    RUNNING = "running"
    DONE = "done"
    REJECTED = "rejected"
    ERROR = "error"


class DiagnosticCode(StrEnum):
    """Codes of non-fatal reducer diagnostics (API §11). Values equal names."""

    UNKNOWN_EVENT_TYPE = "UNKNOWN_EVENT_TYPE"
    INVALID_EVENT = "INVALID_EVENT"
    IMPLICIT_MESSAGE = "IMPLICIT_MESSAGE"
    UNKNOWN_MESSAGE_ID = "UNKNOWN_MESSAGE_ID"
    UNKNOWN_TOOL_CALL_ID = "UNKNOWN_TOOL_CALL_ID"
    DUPLICATE_ID = "DUPLICATE_ID"
    STALE_RUN_EVENT = "STALE_RUN_EVENT"
    PATCH_FAILED = "PATCH_FAILED"
    ARGS_TOO_LARGE = "ARGS_TOO_LARGE"
    IGNORED_EVENT = "IGNORED_EVENT"


def _restore(cls: type[TolerantPickle], state: dict[str, Any]) -> TolerantPickle:
    """Unpickling entry point: rebuild ``cls`` tolerantly from its pickled state."""
    return cls._from_state(state)


class TolerantPickle:
    """Mixin giving dataclasses a version-tolerant pickle format (DM §8 v1.2).

    The pickled state is ``{"schema_version": n, **fields}``. Restoring fills missing
    fields with their defaults and drops unknown ones, so an older or newer pickle held
    by the state manager (e.g. Redis) still loads after a library upgrade.

    It hooks ``__reduce__`` because ``@dataclass(frozen=True, slots=True)`` installs its
    own ``__getstate__``/``__setstate__`` on every class, shadowing a mixin's.
    """

    __slots__ = ()

    _schema_version: ClassVar[int] = 1
    _derived_fields: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def _persisted_fields(cls) -> tuple[dataclasses.Field[Any], ...]:
        fields = dataclasses.fields(cast("type[DataclassInstance]", cls))
        return tuple(f for f in fields if f.init and f.name not in cls._derived_fields)

    def _to_state(self) -> dict[str, Any]:
        """Return the pickled form: the schema version plus every persisted field."""
        state: dict[str, Any] = {"schema_version": self._schema_version}
        for f in self._persisted_fields():
            state[f.name] = getattr(self, f.name)
        return state

    @classmethod
    def _from_state(cls, state: dict[str, Any]) -> Self:
        """Build an instance from a pickled state, tolerating missing and unknown fields."""
        kwargs: dict[str, Any] = {}
        for f in cls._persisted_fields():
            if f.name in state:
                kwargs[f.name] = state[f.name]
            elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                raise TypeError(
                    f"cannot restore {cls.__name__}: required field {f.name!r} is missing"
                )
        return cls(**kwargs)

    def __reduce__(self) -> tuple[Callable[..., Any], tuple[Any, ...]]:
        return (_restore, (type(self), self._to_state()))


@dataclasses.dataclass(frozen=True, slots=True)
class ChatMessage(TolerantPickle):
    """A conversation message (DM §3.1, API §5.1)."""

    id: str
    role: MessageRole
    content: str = ""
    streaming: bool = False
    tool_call_ids: tuple[str, ...] = ()
    tool_call_id: str | None = None
    reasoning: str = ""
    is_error: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class ToolCall(TolerantPickle):
    """A tool call issued by the agent (DM §3.2, API §5.2)."""

    id: str
    name: str
    args_text: str = ""
    args: JsonObject | None = None
    status: ToolCallStatus = ToolCallStatus.STREAMING
    result: str | None = None
    parent_message_id: str | None = None
    interrupt_id: str | None = None
    is_client_tool: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class PendingInterrupt(TolerantPickle):
    """The generic interrupt shown to the user; computed by ``project()`` (DM §3.3)."""

    id: str
    reason: str
    message: str
    payload: JsonValue
    response_schema: JsonObject | None
    queue_position: int
    queue_size: int


@dataclasses.dataclass(frozen=True, slots=True)
class OpenInterrupt(TolerantPickle):
    """An interrupt of the current pause, or a local client-tool approval (DM §3.4)."""

    id: str
    reason: str
    message: str = ""
    tool_call_id: str | None = None
    payload: JsonValue = None
    response_schema: JsonObject | None = None
    is_local: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class InterruptAnswer(TolerantPickle):
    """The user's answer to an open interrupt, mirroring ``ResumeEntry`` (DM §3.5)."""

    interrupt_id: str
    status: ResumeStatus
    payload: JsonValue = None


@dataclasses.dataclass(frozen=True, slots=True)
class ReasoningRecord(TolerantPickle):
    """Reasoning of one assistant turn (DM §3.6). ``encrypted_value`` is never projected."""

    id: str
    assistant_message_id: str | None = None
    content: str = ""
    encrypted_value: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class CustomEventRecord(TolerantPickle):
    """An AG-UI ``CUSTOM`` event kept in a bounded ring (DM §3.7, API §5.4)."""

    name: str
    value: JsonValue
    run_id: str


@dataclasses.dataclass(frozen=True, slots=True)
class Diagnostic(TolerantPickle):
    """A transient, non-fatal reducer diagnostic (DM §3.8, API §11)."""

    level: DiagnosticLevel
    code: DiagnosticCode
    message: str
    event_type: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class ReducerConfig(TolerantPickle):
    """Per-run reducer settings built from the ``AgentState`` ClassVars (DM §3.9)."""

    client_tool_names: frozenset[str] = frozenset()
    custom_events_limit: int = 100
    max_args_bytes: int = 1_048_576
