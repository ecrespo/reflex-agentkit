"""Hypothesis strategies: plausible-but-chaotic AG-UI event and command sequences (T-018).

IDs come from small pools so collisions, unknown IDs and out-of-order events are
frequent. Events are raw wire dicts (camelCase) run through ``parse_event``; ``$run`` and
``$thread`` are replaced at apply time with the conversation's current IDs, and ``old``
stands for a stale run.
"""

from __future__ import annotations

from typing import Any

from hypothesis import strategies as st

MESSAGE_IDS = st.sampled_from(["m1", "m2", "m3"])
CALL_IDS = st.sampled_from(["c1", "c2", "c3"])
REASONING_IDS = st.sampled_from(["r1", "r2", "m1"])
RUN_IDS = st.sampled_from(["$run", "$run", "$run", "old"])
TOOL_NAMES = st.sampled_from(["get_weather", "pick_date"])
CLIENT_TOOL_NAMES = frozenset({"pick_date"})
TEXT = st.text(alphabet='ab {}":,1', max_size=6)
ARGS_TEXT = st.sampled_from(['{"city": "Lisbon"}', '{"a"', ": 1}", "", "[1]", '{"x": NaN}'])

JSON_SCALARS = st.none() | st.booleans() | st.integers(-3, 3) | st.sampled_from(["x", "y"])
JSON = st.recursive(
    JSON_SCALARS,
    lambda inner: (
        st.lists(inner, max_size=3)
        | st.dictionaries(st.sampled_from(["a", "b", "c"]), inner, max_size=3)
    ),
    max_leaves=6,
)
PATHS = st.sampled_from(["/a", "/b", "/a/0", "/a/b", "/c/-", "/", "/missing/x"])

Step = tuple[str, Any]


def _event(type_: str, **fields: Any) -> st.SearchStrategy[Step]:
    return st.fixed_dictionaries({"type": st.just(type_), **fields}).map(lambda d: ("event", d))


INTERRUPTS = st.lists(
    st.one_of(
        st.fixed_dictionaries(
            {
                "id": st.sampled_from(["i1", "i2", "int-c1"]),
                "reason": st.just("tool_call"),
                "toolCallId": CALL_IDS,
            }
        ),
        st.fixed_dictionaries(
            {
                "id": st.sampled_from(["i1", "i2", "i3"]),
                "reason": st.sampled_from(["human_input", "confirm"]),
                "message": TEXT,
            }
        ),
    ),
    min_size=1,
    max_size=3,
)

OUTCOMES = st.one_of(
    st.none(),
    st.just({"type": "success"}),
    st.fixed_dictionaries(
        {"type": st.just("success"), "pendingToolCallIds": st.lists(CALL_IDS, max_size=2)}
    ),
    st.fixed_dictionaries({"type": st.just("interrupt"), "interrupts": INTERRUPTS}),
    st.just({"type": "cancelled"}),
)


def _run_finished(outcome: dict[str, Any] | None, run_id: str) -> Step:
    event: dict[str, Any] = {"type": "RUN_FINISHED", "threadId": "$thread", "runId": run_id}
    if outcome is not None:
        event["outcome"] = outcome
    return ("event", event)


DELTA_OPS = st.lists(
    st.one_of(
        st.fixed_dictionaries(
            {"op": st.sampled_from(["add", "replace"]), "path": PATHS, "value": JSON}
        ),
        st.fixed_dictionaries({"op": st.just("remove"), "path": PATHS}),
        st.fixed_dictionaries({"op": st.just("test"), "path": PATHS, "value": JSON}),
    ),
    min_size=1,
    max_size=3,
)

SNAPSHOT_MESSAGES = st.lists(
    st.one_of(
        st.fixed_dictionaries({"id": MESSAGE_IDS, "role": st.just("user"), "content": TEXT}),
        st.fixed_dictionaries(
            {
                "id": MESSAGE_IDS,
                "role": st.just("assistant"),
                "content": TEXT,
                "toolCalls": st.lists(
                    st.fixed_dictionaries(
                        {
                            "id": CALL_IDS,
                            "type": st.just("function"),
                            "function": st.fixed_dictionaries(
                                {"name": TOOL_NAMES, "arguments": ARGS_TEXT}
                            ),
                        }
                    ),
                    max_size=2,
                ),
            }
        ),
        st.fixed_dictionaries(
            {"id": MESSAGE_IDS, "role": st.just("tool"), "content": TEXT, "toolCallId": CALL_IDS}
        ),
        st.fixed_dictionaries(
            {
                "id": REASONING_IDS,
                "role": st.just("reasoning"),
                "content": TEXT,
                "encryptedValue": st.sampled_from(["ENC"]),
            }
        ),
    ),
    max_size=4,
)

EVENTS: st.SearchStrategy[Step] = st.one_of(
    _event("RUN_STARTED", threadId=st.just("$thread"), runId=RUN_IDS),
    st.builds(_run_finished, OUTCOMES, RUN_IDS),
    _event("RUN_ERROR", message=TEXT),
    _event("STEP_STARTED", stepName=st.sampled_from(["plan", "act"])),
    _event("STEP_FINISHED", stepName=st.sampled_from(["plan", "act"])),
    _event("TEXT_MESSAGE_START", messageId=MESSAGE_IDS, role=st.just("assistant")),
    _event("TEXT_MESSAGE_CONTENT", messageId=MESSAGE_IDS, delta=TEXT.filter(bool)),
    _event("TEXT_MESSAGE_END", messageId=MESSAGE_IDS),
    _event("TEXT_MESSAGE_CHUNK", messageId=MESSAGE_IDS, delta=TEXT),
    _event(
        "TOOL_CALL_START", toolCallId=CALL_IDS, toolCallName=TOOL_NAMES, parentMessageId=MESSAGE_IDS
    ),
    _event("TOOL_CALL_START", toolCallId=CALL_IDS, toolCallName=TOOL_NAMES),
    _event("TOOL_CALL_ARGS", toolCallId=CALL_IDS, delta=ARGS_TEXT),
    _event("TOOL_CALL_END", toolCallId=CALL_IDS),
    _event("TOOL_CALL_CHUNK", toolCallId=CALL_IDS, toolCallName=TOOL_NAMES, delta=ARGS_TEXT),
    _event("TOOL_CALL_CHUNK", delta=ARGS_TEXT),
    _event(
        "TOOL_CALL_RESULT",
        messageId=st.sampled_from(["t1", "t2"]),
        toolCallId=CALL_IDS,
        content=TEXT,
    ),
    _event("STATE_SNAPSHOT", snapshot=JSON),
    _event("STATE_DELTA", delta=DELTA_OPS),
    _event("MESSAGES_SNAPSHOT", messages=SNAPSHOT_MESSAGES),
    _event("CUSTOM", name=st.sampled_from(["progress"]), value=JSON),
    _event("RAW", event=JSON),
    _event("REASONING_MESSAGE_START", messageId=REASONING_IDS, role=st.just("reasoning")),
    _event("REASONING_MESSAGE_CONTENT", messageId=REASONING_IDS, delta=TEXT.filter(bool)),
    _event("REASONING_MESSAGE_END", messageId=REASONING_IDS),
    _event("REASONING_MESSAGE_CHUNK", messageId=REASONING_IDS, delta=TEXT),
    _event(
        "REASONING_ENCRYPTED_VALUE",
        subtype=st.sampled_from(["message", "tool-call"]),
        entityId=st.one_of(REASONING_IDS, CALL_IDS),
        encryptedValue=st.just("ENC"),
    ),
    st.just(("event", {"type": "NOT_A_TYPE"})),
    st.just(("event", {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1"})),
)

COMMANDS: st.SearchStrategy[Step] = st.one_of(
    st.fixed_dictionaries({"user_text": TEXT}).map(lambda k: ("begin_run", k)),
    st.just(("begin_run", {"resume": True})),
    st.fixed_dictionaries(
        {"call_id": CALL_IDS, "edited_args": st.one_of(st.none(), JSON, ARGS_TEXT)}
    ).map(lambda k: ("apply_approval", k)),
    st.fixed_dictionaries({"call_id": CALL_IDS, "reason": st.one_of(st.none(), TEXT)}).map(
        lambda k: ("apply_rejection", k)
    ),
    st.fixed_dictionaries({"payload": st.one_of(JSON, TEXT)}).map(
        lambda k: ("apply_interrupt_response", k)
    ),
    st.just(("apply_cancel", {})),
    st.fixed_dictionaries({"call_id": CALL_IDS, "result": TEXT, "is_error": st.booleans()}).map(
        lambda k: ("apply_client_tool_result", k)
    ),
    st.just(("new_thread", {})),
)


@st.composite
def _tool_round(draw: st.DrawFn) -> list[Step]:
    """A complete call: START, valid ARGS, END (so pauses can link to it)."""
    call_id = draw(CALL_IDS)
    start = {"type": "TOOL_CALL_START", "toolCallId": call_id, "toolCallName": draw(TOOL_NAMES)}
    args = {"type": "TOOL_CALL_ARGS", "toolCallId": call_id, "delta": '{"city": "Lisbon"}'}
    end = {"type": "TOOL_CALL_END", "toolCallId": call_id}
    return [("event", start), ("event", args), ("event", end)]


@st.composite
def _pause(draw: st.DrawFn) -> list[Step]:
    """A run that ends paused on approvals for known calls and/or generic interrupts."""
    steps = draw(_tool_round())
    call_id = steps[0][1]["toolCallId"]
    interrupts: list[dict[str, Any]] = [
        {"id": f"int-{call_id}", "reason": "tool_call", "toolCallId": call_id}
    ]
    if draw(st.booleans()):
        interrupts.append({"id": draw(st.sampled_from(["i1", "i2"])), "reason": "human_input"})
    finished = {
        "type": "RUN_FINISHED",
        "threadId": "$thread",
        "runId": "$run",
        "outcome": {"type": "interrupt", "interrupts": draw(st.permutations(interrupts))},
    }
    return [*steps, ("event", finished)]


@st.composite
def _answered_pause(draw: st.DrawFn) -> list[Step]:
    """A pause followed by answers for its call (and interrupts), maybe a resume."""
    steps = draw(_pause())
    call_id = steps[0][1]["toolCallId"]
    answer = draw(
        st.sampled_from(
            [
                ("apply_approval", {"call_id": call_id}),
                ("apply_approval", {"call_id": call_id, "edited_args": '{"city": "Porto"}'}),
                ("apply_rejection", {"call_id": call_id, "reason": "no"}),
                ("apply_cancel", {}),
            ]
        )
    )
    tail: list[Step] = [answer, ("apply_interrupt_response", {"payload": "yes"})]
    if draw(st.booleans()):
        tail.append(("begin_run", {"resume": True}))
    return [*steps, *tail]


_FRAGMENTS: st.SearchStrategy[list[Step]] = st.one_of(
    EVENTS.map(lambda step: [step]),
    EVENTS.map(lambda step: [step]),
    EVENTS.map(lambda step: [step]),
    COMMANDS.map(lambda step: [step]),
    _tool_round(),
    _pause(),
    _answered_pause(),
)

STEPS: st.SearchStrategy[list[Step]] = st.lists(_FRAGMENTS, min_size=1, max_size=20).map(
    lambda fragments: [step for fragment in fragments for step in fragment]
)
