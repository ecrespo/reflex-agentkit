"""NFR-01: library overhead per event, the reducer micro-benchmark (T-049, DM §5).

A conversation of 500 messages receives 10,000 text deltas. Each event is measured from
the wire dict to the applied state (``parse_event`` + ``reduce``). Target: p95 < 1 ms.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

import pytest
from ag_ui.core import BaseEvent

from reflex_agentkit.core import ConversationState, reduce
from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.models import ReducerConfig
from reflex_agentkit.core.reducer import parse_event

pytestmark = pytest.mark.bench

HISTORY = 500
DELTAS = 10_000
P95_BUDGET_S = 0.001


def _apply(conv: ConversationState, raw: dict[str, Any]) -> ConversationState:
    event = parse_event(raw)
    assert isinstance(event, BaseEvent)
    return reduce(conv, event)


def _history() -> ConversationState:
    conv = begin_run(ConversationState(config=ReducerConfig()), config=ReducerConfig())
    conv = _apply(conv, {"type": "RUN_STARTED", "threadId": conv.thread_id, "runId": conv.run_id})
    for i in range(HISTORY):
        role = "user" if i % 2 == 0 else "assistant"
        conv = _apply(conv, {"type": "TEXT_MESSAGE_START", "messageId": f"h{i}", "role": role})
        delta = f"message {i} " * 20
        conv = _apply(conv, {"type": "TEXT_MESSAGE_CONTENT", "messageId": f"h{i}", "delta": delta})
        conv = _apply(conv, {"type": "TEXT_MESSAGE_END", "messageId": f"h{i}"})
    return _apply(conv, {"type": "TEXT_MESSAGE_START", "messageId": "live", "role": "assistant"})


def test_NFR_01_reducer_p95_under_one_millisecond() -> None:
    """NFR-01: p95 per event < 1 ms with 500 messages and 10k content deltas."""
    conv = _history()
    assert len(conv.messages) == HISTORY + 1
    timings: list[float] = []
    for i in range(DELTAS):
        raw = {"type": "TEXT_MESSAGE_CONTENT", "messageId": "live", "delta": f"tok{i} "}
        start = time.perf_counter()
        conv = _apply(conv, raw)
        timings.append(time.perf_counter() - start)
    assert conv.messages[-1].content.endswith(f"tok{DELTAS - 1} ")
    p95 = statistics.quantiles(timings, n=100)[94]
    print(
        f"\nNFR-01 reducer: p50 {statistics.median(timings) * 1e6:.0f} µs, p95 {p95 * 1e6:.0f} µs"
    )
    assert p95 < P95_BUDGET_S
