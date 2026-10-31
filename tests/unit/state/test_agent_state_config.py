"""``AgentState`` configuration, vars and computed vars (T-029, API §4.1-4.2, DD-006)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pydantic
import pytest
import reflex as rx
from ag_ui.core import BaseEvent, RunAgentInput
from helpers.reflex_harness import ReflexHarness

from reflex_agentkit import AgentState
from reflex_agentkit.core.clients.base import AgentClient
from reflex_agentkit.core.clients.in_process import InProcessAGUIClient
from reflex_agentkit.core.errors import ConfigurationError
from reflex_agentkit.core.models import RunStatus, ToolCall, ToolCallStatus
from reflex_agentkit.core.tools import client_tool


class _Agent:
    """A minimal ``AGUIAgent``."""

    async def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        return
        yield  # pragma: no cover


@client_tool
def pick(day: int) -> str:
    """Pick a day."""
    return str(day)


class ConfiguredState(AgentState, rx.State):
    agent: ClassVar = _Agent()
    client_tools: ClassVar = (pick,)
    flush_interval_ms: ClassVar = 0


def test_API_4_1_defaults() -> None:
    """API §4.1: the documented defaults."""
    assert ConfiguredState.flush_interval_ms == 0
    assert AgentState.flush_interval_ms == 50
    assert AgentState.max_message_length == 32_000
    assert AgentState.client_tool_timeout_s == 30.0
    assert AgentState.custom_events_limit == 100
    assert AgentState.max_client_tool_rounds == 8
    assert AgentState.client_tools == ()
    assert AgentState.shared_state_model is None


def test_DD_006_class_vars_are_not_state_vars() -> None:
    """DD-006, REQ-025.1: configuration is never a var, so never sent to the browser."""
    for name in ("agent", "client_tools", "flush_interval_ms", "shared_state_model"):
        assert name not in ConfiguredState.base_vars
        assert name not in ConfiguredState.computed_vars
    assert "_conv" not in ConfiguredState.base_vars


def test_API_4_2_public_vars_are_declared() -> None:
    """API §4.2: the public vars and the computed vars."""
    public = {
        "messages",
        "tool_calls",
        "pending_interrupt",
        "shared_state",
        "shared_state_stale",
        "run_status",
        "current_step",
        "thread_id",
        "run_id",
        "error",
        "error_code",
        "custom_events",
    }
    assert public <= set(ConfiguredState.base_vars)
    computed = {"is_running", "awaiting_input", "pending_approvals", "can_send"}
    assert computed <= set(ConfiguredState.computed_vars)


def test_REQ_021_agent_is_wrapped_in_an_in_process_client() -> None:
    """API §4.4: the default ``create_client`` wraps an ``AGUIAgent``."""
    state = ConfiguredState(_reflex_internal_init=True)  # type: ignore[call-arg]
    assert isinstance(state.create_client(), InProcessAGUIClient)


def test_REQ_021_an_agent_client_is_used_as_is() -> None:
    """API §4.1: an ``AgentClient`` is returned unchanged."""
    client = InProcessAGUIClient(_Agent())

    class ClientState(AgentState, rx.State):
        agent: ClassVar = client

    state = ClientState(_reflex_internal_init=True)  # type: ignore[call-arg]
    assert state.create_client() is client


def test_API_4_1_missing_agent_is_a_configuration_error() -> None:
    """API §4.1: no ``agent`` and no ``create_client`` override fails at definition."""
    with pytest.raises(ConfigurationError, match="agent"):

        class NoAgentState(AgentState, rx.State):
            pass


def test_API_4_1_create_client_override_needs_no_agent() -> None:
    """API §4.4: overriding ``create_client`` replaces ``agent``."""

    class CustomClientState(AgentState, rx.State):
        def create_client(self) -> AgentClient:
            return InProcessAGUIClient(_Agent())

    assert CustomClientState.agent is None


def test_API_4_1_agent_of_the_wrong_type_is_a_configuration_error() -> None:
    """API §4.1: ``agent`` must be an ``AgentClient`` or an ``AGUIAgent``."""
    with pytest.raises(ConfigurationError, match="agent"):

        class WrongAgentState(AgentState, rx.State):
            agent: ClassVar = "not an agent"  # type: ignore[assignment]


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("flush_interval_ms", -1),
        ("max_message_length", 0),
        ("client_tool_timeout_s", 0),
        ("custom_events_limit", 0),
        ("max_client_tool_rounds", 0),
    ],
)
def test_API_4_1_invalid_limits_are_configuration_errors(name: str, value: object) -> None:
    """API §4.1: a negative interval (and other out-of-range limits) fail at definition."""
    namespace: dict[str, Any] = {
        "__annotations__": {"agent": "ClassVar", name: "ClassVar"},
        "agent": _Agent(),
        name: value,
        "__module__": __name__,
    }
    with pytest.raises(ConfigurationError, match=name):
        type(f"Bad_{name}_State", (AgentState, rx.State), namespace)


def test_API_4_1_duplicate_client_tool_names_are_a_configuration_error() -> None:
    """API §4.1: two client tools with the same name fail at definition."""
    with pytest.raises(ConfigurationError, match="client_tools"):

        class DuplicateToolsState(AgentState, rx.State):
            agent: ClassVar = _Agent()
            client_tools: ClassVar = (pick, pick)


def test_API_4_1_client_tools_must_be_client_tools() -> None:
    """API §4.1: ``client_tools`` holds ``ClientTool`` objects (``@client_tool``)."""
    with pytest.raises(ConfigurationError, match="client_tools"):

        class PlainFunctionToolsState(AgentState, rx.State):
            agent: ClassVar = _Agent()
            client_tools: ClassVar = (len,)  # type: ignore[assignment]


def test_API_4_1_shared_state_model_must_be_a_base_model() -> None:
    """API §4.1: ``shared_state_model`` must be a ``pydantic.BaseModel`` subclass."""
    with pytest.raises(ConfigurationError, match="shared_state_model"):

        class WrongModelState(AgentState, rx.State):
            agent: ClassVar = _Agent()
            shared_state_model: ClassVar = dict  # type: ignore[assignment]

    class Model(pydantic.BaseModel):
        count: int = 0

    class ModelState(AgentState, rx.State):
        agent: ClassVar = _Agent()
        shared_state_model: ClassVar = Model

    assert ModelState.shared_state_model is Model


def test_DD_006_unannotated_agent_fails_at_definition() -> None:
    """TD §8.4.4: without ``ClassVar`` Reflex makes ``agent`` a var, which fails loudly."""
    with pytest.raises(Exception, match=r"(?i)agent|serializable|var"):

        class UnannotatedState(AgentState, rx.State):
            agent = _Agent()


def test_DD_006_a_mixin_subclass_is_not_validated() -> None:
    """A further mixin (``mixin=True``) is configured later by its own subclasses."""

    class MoreMixin(AgentState, mixin=True):
        flush_interval_ms: ClassVar = 10

    class FinalState(MoreMixin, rx.State):
        agent: ClassVar = _Agent()

    assert FinalState.flush_interval_ms == 10


async def test_API_4_2_initial_values_and_computed_vars(reflex_harness: ReflexHarness) -> None:
    """API §4.2: initial public values; computed vars follow ``run_status``."""
    state = await reflex_harness.state("tok-init", ConfiguredState)
    assert state.messages == []
    assert state.tool_calls == []
    assert state.pending_interrupt is None
    assert state.shared_state == {}
    assert state.run_status == RunStatus.IDLE
    assert (state.thread_id, state.run_id, state.error) == ("", "", "")
    assert state.error_code is None
    assert state.custom_events == []
    assert (state.is_running, state.awaiting_input, state.can_send) == (False, False, True)
    assert state.pending_approvals == []
    state.run_status = RunStatus.AWAITING_INPUT
    state.tool_calls = [
        ToolCall(id="c1", name="a", status=ToolCallStatus.DONE),
        ToolCall(id="c2", name="b", status=ToolCallStatus.PENDING_APPROVAL),
    ]
    assert (state.is_running, state.awaiting_input, state.can_send) == (False, True, False)
    assert [c.id for c in state.pending_approvals] == ["c2"]
