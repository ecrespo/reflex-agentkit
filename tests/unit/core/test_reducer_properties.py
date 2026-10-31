"""Property tests of the reducer and commands (T-018, REQ-005.1-2, DM §4)."""

from __future__ import annotations

import copy
import itertools
from typing import Any

from helpers.fixtures import substitute
from helpers.invariants import check_invariants
from helpers.strategies import CLIENT_TOOL_NAMES, STEPS, Step
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from reflex_agentkit.core import commands
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import Diagnostic, ReducerConfig
from reflex_agentkit.core.reducer import parse_event, reduce

CONFIG = ReducerConfig(
    client_tool_names=CLIENT_TOOL_NAMES, custom_events_limit=3, max_args_bytes=64
)
PROPERTY_SETTINGS = settings(
    max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
ID_COMMANDS = {"begin_run", "apply_rejection", "apply_client_tool_result", "new_thread"}


def _run(steps: list[Step], *, check_mutation: bool = False) -> list[ConversationState]:
    """Apply ``steps`` from a fresh conversation; return the state after every step."""
    counter = itertools.count()

    def new_id() -> str:
        return f"id-{next(counter)}"

    conv = commands.begin_run(
        ConversationState.initial(CONFIG), config=CONFIG, user_text="go", new_id=new_id
    )
    states = [conv]
    for kind, payload in steps:
        if kind == "event":
            raw = substitute(payload, {"$run": conv.run_id, "$thread": conv.thread_id or "t"})
            parsed = parse_event(raw)
            if isinstance(parsed, Diagnostic):
                continue
            before = copy.deepcopy(conv) if check_mutation else None
            event_dump = parsed.model_dump() if check_mutation else None
            new = reduce(conv, parsed)
            if check_mutation:
                assert conv == before, "INV-12: reduce mutated its input state"
                assert parsed.model_dump() == event_dump, "INV-12: reduce mutated the event"
        else:
            kwargs: dict[str, Any] = dict(payload)
            if kind in ID_COMMANDS:
                kwargs["new_id"] = new_id
            if kind == "begin_run":
                kwargs["config"] = CONFIG
            before = copy.deepcopy(conv) if check_mutation else None
            new = getattr(commands, kind)(conv, **kwargs)
            if check_mutation:
                assert conv == before, f"INV-12: {kind} mutated its input state"
        check_invariants(new)
        conv = new.with_(diagnostics=()) if new.diagnostics else new
        states.append(conv)
    return states


@PROPERTY_SETTINGS
@given(STEPS)
def test_REQ_005_1_reducer_and_commands_are_total(steps: list[Step]) -> None:
    """REQ-005.1, DM §4: no exception, and INV-1…INV-11 hold after every step."""
    _run(steps)


@PROPERTY_SETTINGS
@given(STEPS)
def test_REQ_005_2_replay_is_deterministic(steps: list[Step]) -> None:
    """REQ-005.2: the same sequence (and ID factory) gives equal states."""
    assert _run(steps) == _run(steps)


@PROPERTY_SETTINGS
@given(STEPS)
def test_DM_INV_12_inputs_are_never_mutated(steps: list[Step]) -> None:
    """INV-12: neither ``reduce`` nor a command mutates the state or the event it gets."""
    _run(steps, check_mutation=True)


@PROPERTY_SETTINGS
@given(STEPS, st.integers(0, 39))
def test_REQ_005_2_pickling_round_trips_mid_sequence(steps: list[Step], cut: int) -> None:
    """DM §8: a state pickled mid-sequence (e.g. by Redis) restores equal."""
    import pickle

    states = _run(steps)
    state = states[min(cut, len(states) - 1)]
    assert pickle.loads(pickle.dumps(state)) == state  # noqa: S301
