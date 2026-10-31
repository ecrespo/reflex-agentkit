"""Fixture replay (DM §10, REQ-005.3) and unit tests of the fixture loader itself."""

from __future__ import annotations

import dataclasses
import json
import types
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from ag_ui.core import BaseEvent, Event, RunStartedEvent, TextMessageContentEvent
from helpers.fixtures import (
    CommandStep,
    Engine,
    EventStep,
    FixtureFormatError,
    ReplayResult,
    assert_fixture,
    check_expect,
    discover_fixtures,
    fixture_ids,
    load_fixture,
    replay,
    substitute,
    view_of,
)
from pydantic import TypeAdapter, ValidationError

from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import (
    ChatMessage,
    Diagnostic,
    DiagnosticCode,
    MessageRole,
    ReducerConfig,
    RunStatus,
)

FIXTURES = discover_fixtures()


@pytest.mark.parametrize("path", FIXTURES, ids=fixture_ids(FIXTURES))
def test_REQ_005_3_fixture_replays_to_its_expected_state(path: Path, record_property: Any) -> None:
    """REQ-005.3: every JSONL fixture replays through ``reduce`` to its ``expect``."""
    fixture = load_fixture(path)
    record_property("reqs", ",".join(fixture.reqs))
    assert_fixture(fixture)


# --- a fake engine, so the loader is tested before the reducer exists ----------------------

_ADAPTER: TypeAdapter[Any] = TypeAdapter(Event)


def _fake_parse(raw: Mapping[str, Any]) -> BaseEvent | Diagnostic:
    try:
        event: BaseEvent = _ADAPTER.validate_python(raw)
    except ValidationError:
        return Diagnostic(level="warning", code=DiagnosticCode.INVALID_EVENT, message="bad")
    return event


def _fake_reduce(conv: ConversationState, event: BaseEvent) -> ConversationState:
    if isinstance(event, RunStartedEvent):
        if event.run_id not in conv.last_run_ids:
            diag = Diagnostic(
                level="warning", code=DiagnosticCode.STALE_RUN_EVENT, message=event.run_id
            )
            return conv.with_(diagnostics=(*conv.diagnostics, diag))
        return conv
    if isinstance(event, TextMessageContentEvent):
        msg = ChatMessage(id=event.message_id, role=MessageRole.ASSISTANT, content=event.delta)
        return conv.with_(messages=(*conv.messages, msg))
    return conv


def _fake_begin_run(
    conv: ConversationState,
    *,
    config: ReducerConfig,
    user_text: str | None = None,
    resume: bool = False,
) -> ConversationState:
    run_id = f"run-{len(conv.last_run_ids) + 1}"
    messages = conv.messages
    if user_text is not None:
        messages = (
            *messages,
            ChatMessage(id=f"u-{run_id}", role=MessageRole.USER, content=user_text),
        )
    return conv.with_(
        config=config,
        thread_id=conv.thread_id or "thread-1",
        run_id=run_id,
        last_run_ids=(*conv.last_run_ids, run_id),
        messages=messages,
    )


def _fake_cancel(conv: ConversationState) -> ConversationState:
    return conv.with_(run_status=RunStatus.CANCELLED)


FAKE = Engine(
    reduce=_fake_reduce,
    parse_event=_fake_parse,
    commands=types.SimpleNamespace(begin_run=_fake_begin_run, apply_cancel=_fake_cancel),
)


def _write(tmp_path: Path, name: str, lines: list[Any]) -> Path:
    path = tmp_path / f"{name}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


HEADER = {"fixture": "demo", "reqs": ["REQ-000.1"], "start": {"user_text": "hi"}, "expect": {}}


# --- loading ------------------------------------------------------------------------------


def test_DM_10_loader_parses_header_events_and_commands(tmp_path: Path) -> None:
    """DM §10: header fields, event lines and ``$command`` lines are parsed."""
    path = _write(
        tmp_path,
        "demo",
        [
            {**HEADER, "config": {"client_tool_names": ["pick"]}},
            {"type": "RUN_STARTED", "threadId": "$thread", "runId": "$run"},
            {"$command": "approve_tool", "call_id": "c1", "edited_args": {"x": 1}},
        ],
    )
    fixture = load_fixture(path)
    assert fixture.name == "demo"
    assert fixture.reqs == ("REQ-000.1",)
    assert fixture.config == {"client_tool_names": ["pick"]}
    assert fixture.start == {"user_text": "hi"}
    assert fixture.steps == (
        EventStep(raw={"type": "RUN_STARTED", "threadId": "$thread", "runId": "$run"}),
        CommandStep(name="approve_tool", kwargs={"call_id": "c1", "edited_args": {"x": 1}}),
    )


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        ([{"fixture": "demo", "reqs": []}], "expect"),
        ([{**HEADER, "fixture": "other"}], "expected 'demo'"),
        ([HEADER, {"$command": "launch_rockets"}], "unknown command"),
        ([HEADER, [1, 2]], "JSON object"),
    ],
    ids=["missing-expect", "name-mismatch", "unknown-command", "non-object-line"],
)
def test_DM_10_loader_rejects_malformed_fixtures(
    tmp_path: Path, lines: list[Any], message: str
) -> None:
    """DM §10: malformed fixtures fail loudly instead of passing vacuously."""
    with pytest.raises(FixtureFormatError, match=message):
        load_fixture(_write(tmp_path, "demo", lines))


def test_DM_10_loader_rejects_invalid_json(tmp_path: Path) -> None:
    """DM §10: a line that is not JSON is a format error."""
    path = tmp_path / "demo.jsonl"
    path.write_text(json.dumps(HEADER) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(FixtureFormatError, match="invalid JSON"):
        load_fixture(path)


def test_DM_10_discovery_returns_sorted_jsonl_files(tmp_path: Path) -> None:
    """REQ-005.3: every ``*.jsonl`` file in the directory is a fixture."""
    for name in ("b", "a"):
        _write(tmp_path, name, [{**HEADER, "fixture": name}])
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    paths = discover_fixtures(tmp_path)
    assert fixture_ids(paths) == ["a", "b"]


# --- placeholders and replay --------------------------------------------------------------


def test_DM_10_substitute_replaces_exact_placeholders_recursively() -> None:
    """DM §10: ``$thread``/``$run``/``$run2`` are replaced wherever they appear as values."""
    mapping = {"$thread": "t", "$run": "r1", "$run2": "r2"}
    raw = {"threadId": "$thread", "nested": [{"runId": "$run2"}], "text": "$run and more"}
    assert substitute(raw, mapping) == {
        "threadId": "t",
        "nested": [{"runId": "r2"}],
        "text": "$run and more",
    }


def test_DM_10_replay_substitutes_ids_assigned_by_begin_run(tmp_path: Path) -> None:
    """DM §10: events using ``$run`` reach the reducer with the real run ID."""
    path = _write(
        tmp_path,
        "demo",
        [HEADER, {"type": "RUN_STARTED", "threadId": "$thread", "runId": "$run"}],
    )
    result = replay(load_fixture(path), FAKE)
    assert result.run_ids == ("run-1",)
    assert result.diagnostic_codes == ()
    assert result.conv.thread_id == "thread-1"


def test_DM_10_replay_tracks_a_second_run_as_run2(tmp_path: Path) -> None:
    """DM §10: a ``begin_run`` command line assigns ``$run2``."""
    path = _write(
        tmp_path,
        "demo",
        [
            HEADER,
            {"$command": "begin_run", "resume": True},
            {"type": "RUN_STARTED", "threadId": "$thread", "runId": "$run2"},
            {"type": "RUN_STARTED", "threadId": "$thread", "runId": "stale"},
        ],
    )
    result = replay(load_fixture(path), FAKE)
    assert result.run_ids == ("run-1", "run-2")
    assert result.diagnostic_codes == ("STALE_RUN_EVENT",)


def test_DM_10_replay_runs_command_lines(tmp_path: Path) -> None:
    """DM §10: ``$command`` lines call the mapped pure command function."""
    path = _write(tmp_path, "demo", [HEADER, {"$command": "cancel_run"}])
    assert replay(load_fixture(path), FAKE).conv.run_status is RunStatus.CANCELLED


def test_REQ_012_3_replay_keeps_invalid_lines_as_diagnostics(tmp_path: Path) -> None:
    """REQ-012.3: a line failing validation yields ``INVALID_EVENT`` and the replay goes on."""
    path = _write(
        tmp_path,
        "demo",
        [
            HEADER,
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m2", "delta": "ok"},
        ],
    )
    result = replay(load_fixture(path), FAKE)
    assert result.diagnostic_codes == ("INVALID_EVENT",)
    assert [m.id for m in result.conv.messages] == ["u-run-1", "m2"]


def test_DM_10_replay_checks_invariants_after_every_step(tmp_path: Path) -> None:
    """DM §4: a step that breaks an invariant fails the replay."""
    path = _write(
        tmp_path,
        "demo",
        [
            HEADER,
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "dup", "delta": "a"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "dup", "delta": "b"},
        ],
    )
    with pytest.raises(AssertionError, match="INV-1"):
        replay(load_fixture(path), FAKE)


def test_DM_10_replay_builds_the_reducer_config_from_the_header(tmp_path: Path) -> None:
    """DM §10: the header ``config`` becomes the run's ``ReducerConfig``."""
    path = _write(tmp_path, "demo", [{**HEADER, "config": {"client_tool_names": ["pick"]}}])
    config = replay(load_fixture(path), FAKE).conv.config
    assert config.client_tool_names == frozenset({"pick"})


# --- partial matching ---------------------------------------------------------------------


def _view() -> dict[str, Any]:
    conv = ConversationState.initial(ReducerConfig()).with_(
        run_status=RunStatus.RUNNING,
        messages=(
            ChatMessage(id="u1", role=MessageRole.USER, content="hi"),
            ChatMessage(id="m1", role=MessageRole.ASSISTANT, content="hello"),
        ),
    )
    return view_of(ReplayResult(conv=conv, diagnostic_codes=("IGNORED_EVENT",), run_ids=()))


def test_DM_10_view_serializes_enums_and_hides_private_fields() -> None:
    """DM §10: the view is JSON with enum values and without derived indexes."""
    view = _view()
    json.dumps(view)
    assert view["run_status"] == "running"
    assert "_tool_index" not in view


@pytest.mark.parametrize(
    "expect",
    [
        {"run_status": "running"},
        {"messages.length": 2},
        {"messages.1.content": "hello"},
        {"messages": [{"role": "user"}, {"id": "m1"}]},
        {"diagnostics.codes": ["IGNORED_EVENT"]},
        {"config": {"max_args_bytes": 1_048_576}},
    ],
)
def test_DM_10_partial_match_accepts_matching_expectations(expect: dict[str, Any]) -> None:
    """DM §10: dotted paths, ``.length``, partial objects and ``diagnostics.codes``."""
    assert check_expect(_view(), expect) == []


@pytest.mark.parametrize(
    "expect",
    [
        {"run_status": "idle"},
        {"messages.length": 3},
        {"messages": [{"role": "user"}]},
        {"messages": [{"role": "user"}, {"id": "m2"}]},
        {"nope.deeper": 1},
        {"messages.0.ghost": 1},
        {"run_status": {"x": 1}},
        {"run_status": [1]},
    ],
)
def test_DM_10_partial_match_reports_mismatches(expect: dict[str, Any]) -> None:
    """DM §10: every mismatch is reported, so a fixture cannot pass vacuously."""
    assert check_expect(_view(), expect) != []


def test_DM_10_assert_fixture_names_the_fixture_and_its_reqs(tmp_path: Path) -> None:
    """REQ-005.3: a failing fixture reports its name and the criteria it covers."""
    header = {**HEADER, "expect": {"run_status": "error"}}
    fixture = load_fixture(_write(tmp_path, "demo", [header]))
    with pytest.raises(AssertionError, match=r"demo \(REQ-000\.1\)"):
        assert_fixture(fixture, FAKE)


def test_DM_10_fixture_dataclasses_are_frozen() -> None:
    """The parsed fixture is immutable, so a replay cannot alter it."""
    step = CommandStep(name="cancel_run", kwargs={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.name = "x"  # type: ignore[misc]
