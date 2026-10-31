"""Contract tests: Reflex behavior the state engine relies on (TD §8.4 item 4).

These pin facts verified against Reflex 0.10.1 (DD-001). A failure after a Reflex
upgrade means DD-006 or REQ-026.1 must be revisited before the pin is raised.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
import reflex as rx
from reflex_base.event.processor.base_state_processor import BaseStateEventProcessor
from reflex_base.event.processor.event_processor import EventProcessor
from reflex_base.utils.exceptions import VarTypeError


class _ContractMixin(rx.State, mixin=True):
    agent: ClassVar[Any] = None
    count: int = 0


def test_DD_006_unannotated_subclass_attribute_becomes_a_var() -> None:
    """TD §8.4 (4), DD-006: an unannotated ``agent = obj`` is turned into a state var.

    The mixin's ``ClassVar`` declaration does not protect it, so Reflex rejects the
    non-serializable value while the class is being created.
    """
    with pytest.raises(VarTypeError):

        class _UnannotatedAgentState(_ContractMixin, rx.State):
            agent = object()


def test_DD_006_explicit_classvar_is_not_a_var() -> None:
    """TD §8.4 (4), DD-006: ``agent: ClassVar = obj`` in the subclass is not a var."""
    sentinel = object()

    class _ClassVarAgentState(_ContractMixin, rx.State):
        agent: ClassVar = sentinel

    assert "agent" not in _ClassVarAgentState.base_vars
    assert "count" in _ClassVarAgentState.base_vars
    assert _ClassVarAgentState.agent is sentinel


def test_REQ_026_1_base_processor_disconnect_cancels_nothing() -> None:
    """TD §8.4 (4), REQ-026.1: the base event processor's disconnect hook is a no-op."""
    assert EventProcessor._on_disconnect.__code__.co_names == ()


def test_REQ_026_1_state_processor_disconnect_only_cancels_page_load_chains() -> None:
    """TD §8.4 (4), REQ-026.1: on disconnect Reflex cancels hydration/on_load chains only.

    A background run started from a user event is not among them, so it keeps applying
    events to the client's state until it ends.
    """
    names = set(BaseStateEventProcessor._on_disconnect.__code__.co_names)
    assert names >= {"_pending_hydrates", "_superseded"}
    assert not names & {"_tasks", "_futures", "_token_queues"}


def test_TD_6_1_public_methods_become_handlers_unless_flagged() -> None:
    """TD §6.1: Reflex registers every public method as a browser-callable handler, and
    skips functions flagged ``__override_base_method__`` (AgentState flags its hooks)."""

    def flagged(self: Any) -> None:
        pass

    flagged.__override_base_method__ = True  # type: ignore[attr-defined]

    class _HandlerFacts(rx.State):
        count: int = 0

        def plain(self) -> None:
            pass

        hidden = flagged

    assert "plain" in _HandlerFacts.event_handlers
    assert "hidden" not in _HandlerFacts.event_handlers
    assert not hasattr(_HandlerFacts, "set_count")  # no auto-setters for setvar
