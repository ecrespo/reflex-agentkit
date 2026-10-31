"""The ``ConversationState`` aggregate: the single source of truth of a conversation.

It lives in the backend-only Reflex var ``_conv`` (DM §1, §3.10) and is only ever
replaced, never mutated: the reducer and the commands build new instances through
:meth:`ConversationState.with_`, which also rebuilds the derived lookup indexes.
"""

from __future__ import annotations

import dataclasses
from typing import Any, ClassVar, Self

from reflex_agentkit.core.errors import ErrorCode
from reflex_agentkit.core.models import (
    ChatMessage,
    CustomEventRecord,
    Diagnostic,
    InterruptAnswer,
    JsonObject,
    OpenInterrupt,
    ReasoningRecord,
    ReducerConfig,
    RunStatus,
    TolerantPickle,
    ToolCall,
)

__all__ = ["ConversationState"]

SCHEMA_VERSION = 1


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class ConversationState(TolerantPickle):
    """Everything the reducer knows about one conversation (DM §3.10)."""

    _schema_version: ClassVar[int] = SCHEMA_VERSION
    _derived_fields: ClassVar[frozenset[str]] = frozenset({"_tool_index", "_message_index"})

    config: ReducerConfig
    schema_version: int = SCHEMA_VERSION
    thread_id: str = ""
    run_id: str = ""
    run_status: RunStatus = RunStatus.IDLE
    error: str = ""
    error_code: ErrorCode | None = None
    current_step: str = ""
    messages: tuple[ChatMessage, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    reasoning: tuple[ReasoningRecord, ...] = ()
    shared_state: JsonObject = dataclasses.field(default_factory=dict)
    shared_state_stale: bool = False
    interrupts: tuple[OpenInterrupt, ...] = ()
    answers: dict[str, InterruptAnswer] = dataclasses.field(default_factory=dict)
    abandoned_interrupt_ids: tuple[str, ...] = ()
    resume: tuple[InterruptAnswer, ...] = ()
    custom_events: tuple[CustomEventRecord, ...] = ()
    client_tool_rounds: int = 0
    last_run_ids: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    dirty_tool_args: frozenset[str] = frozenset()

    # Derived lookups (H-1, H-2): rebuilt on construction, excluded from == and pickle.
    _tool_index: dict[str, int] = dataclasses.field(
        init=False, compare=False, repr=False, default_factory=dict
    )
    _message_index: dict[str, int] = dataclasses.field(
        init=False, compare=False, repr=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "_tool_index", {c.id: i for i, c in enumerate(self.tool_calls)})
        object.__setattr__(self, "_message_index", {m.id: i for i, m in enumerate(self.messages)})

    @classmethod
    def initial(cls, config: ReducerConfig) -> Self:
        """Return an idle, empty conversation that uses ``config``."""
        return cls(config=config)

    def with_(self, **changes: Any) -> Self:
        """Return a copy with ``changes`` applied and the derived indexes rebuilt."""
        return dataclasses.replace(self, **changes)

    @classmethod
    def _from_state(cls, state: dict[str, Any]) -> Self:
        """Restore tolerantly (DM §8), upgrading older payloads to the current schema.

        There are no upgrade steps yet: version 1 is the first. A future version adds
        its steps here, keyed on ``state.get("schema_version", 1)``.
        """
        upgraded = dict(state)
        upgraded["schema_version"] = SCHEMA_VERSION
        return super(ConversationState, cls)._from_state(upgraded)
