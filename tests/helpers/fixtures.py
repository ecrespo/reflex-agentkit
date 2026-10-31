"""Loader and runner for the JSON Lines event fixtures (DM §10, REQ-005.3).

A fixture file is::

    line 1     header: {"fixture", "reqs", "config", "start", "expect"}
    line 2..n  AG-UI wire events (camelCase) or {"$command": name, **kwargs}

Placeholders ``$thread``, ``$run`` and ``$run2`` are replaced at replay time with the IDs
that ``begin_run`` assigned (the first and second distinct run IDs seen).

The runner needs the reducer and the commands. It takes them through an :class:`Engine`
so the loader can be unit-tested before they exist; :func:`default_engine` imports the
real ones lazily.

``expect`` is a partial match on a JSON view of the ``ConversationState`` whose field
names equal the public vars (DM §7.2), plus ``<path>.length`` and ``diagnostics.codes``
(the codes emitted during the replay, collected before each clear).
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ag_ui.core import BaseEvent

from helpers.invariants import check_invariants
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import Diagnostic, ReducerConfig

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "events"
PLACEHOLDERS = ("$thread", "$run", "$run2")

# Fixture command name (the AgentState handler) -> pure function in core.commands.
COMMANDS: dict[str, str] = {
    "begin_run": "begin_run",
    "approve_tool": "apply_approval",
    "reject_tool": "apply_rejection",
    "respond_to_interrupt": "apply_interrupt_response",
    "cancel_run": "apply_cancel",
    "client_tool_result": "apply_client_tool_result",
    "new_thread": "new_thread",
}


class FixtureFormatError(ValueError):
    """A fixture file does not follow the DM §10 format."""


@dataclasses.dataclass(frozen=True)
class EventStep:
    """An AG-UI event line, kept raw until placeholders are substituted."""

    raw: dict[str, Any]


@dataclasses.dataclass(frozen=True)
class CommandStep:
    """A ``{"$command": ...}`` line calling a pure command function."""

    name: str
    kwargs: dict[str, Any]


Step = EventStep | CommandStep


@dataclasses.dataclass(frozen=True)
class Fixture:
    """A parsed fixture file."""

    name: str
    path: Path
    reqs: tuple[str, ...]
    config: dict[str, Any]
    start: dict[str, Any]
    expect: dict[str, Any]
    steps: tuple[Step, ...]


@dataclasses.dataclass(frozen=True)
class Engine:
    """The reducer-side functions a replay needs."""

    reduce: Callable[[ConversationState, BaseEvent], ConversationState]
    parse_event: Callable[[Mapping[str, Any]], BaseEvent | Diagnostic]
    commands: Any  # a module or namespace exposing the functions named in COMMANDS


@dataclasses.dataclass(frozen=True)
class ReplayResult:
    """The final state and the diagnostic codes emitted during a replay."""

    conv: ConversationState
    diagnostic_codes: tuple[str, ...]
    run_ids: tuple[str, ...]


# --- loading -------------------------------------------------------------------------------


def load_fixture(path: Path) -> Fixture:
    """Parse a DM §10 fixture file."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise FixtureFormatError(f"{path.name}: empty fixture")
    try:
        records = [json.loads(ln) for ln in lines]
    except json.JSONDecodeError as exc:
        raise FixtureFormatError(f"{path.name}: invalid JSON: {exc}") from exc

    header, *body = records
    for key in ("fixture", "reqs", "expect"):
        if key not in header:
            raise FixtureFormatError(f"{path.name}: header lacks {key!r}")
    if header["fixture"] != path.stem:
        raise FixtureFormatError(
            f"{path.name}: header names {header['fixture']!r}, expected {path.stem!r}"
        )

    steps: list[Step] = []
    for record in body:
        if not isinstance(record, dict):
            raise FixtureFormatError(f"{path.name}: every line must be a JSON object")
        if "$command" in record:
            kwargs = {k: v for k, v in record.items() if k != "$command"}
            if record["$command"] not in COMMANDS:
                raise FixtureFormatError(f"{path.name}: unknown command {record['$command']!r}")
            steps.append(CommandStep(name=record["$command"], kwargs=kwargs))
        else:
            steps.append(EventStep(raw=record))

    return Fixture(
        name=header["fixture"],
        path=path,
        reqs=tuple(header["reqs"]),
        config=dict(header.get("config", {})),
        start=dict(header.get("start", {})),
        expect=dict(header["expect"]),
        steps=tuple(steps),
    )


def discover_fixtures(directory: Path = FIXTURES_DIR) -> list[Path]:
    """Return every fixture file, sorted by name."""
    return sorted(directory.glob("*.jsonl"))


# --- replay --------------------------------------------------------------------------------


def substitute(value: Any, mapping: Mapping[str, str]) -> Any:
    """Recursively replace placeholder strings (exact matches only)."""
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [substitute(v, mapping) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, mapping) for k, v in value.items()}
    return value


def default_engine() -> Engine:
    """The real reducer, ``parse_event`` and commands, imported lazily."""
    reducer = importlib.import_module("reflex_agentkit.core.reducer")
    commands = importlib.import_module("reflex_agentkit.core.commands")
    return Engine(reduce=reducer.reduce, parse_event=reducer.parse_event, commands=commands)


def build_config(raw: Mapping[str, Any]) -> ReducerConfig:
    """Build a ``ReducerConfig`` from the header's ``config`` subset."""
    kwargs = dict(raw)
    if "client_tool_names" in kwargs:
        kwargs["client_tool_names"] = frozenset(kwargs["client_tool_names"])
    return ReducerConfig(**kwargs)


def replay(fixture: Fixture, engine: Engine | None = None) -> ReplayResult:
    """Replay ``fixture`` and return the final state and the emitted diagnostic codes.

    Invariants are checked after every step.
    """
    engine = engine or default_engine()
    config = build_config(fixture.config)
    conv = ConversationState.initial(config)
    codes: list[str] = []
    run_ids: list[str] = []

    def settle(new: ConversationState) -> ConversationState:
        codes.extend(str(d.code) for d in new.diagnostics)
        new = new.with_(diagnostics=()) if new.diagnostics else new
        if new.run_id and new.run_id not in run_ids:
            run_ids.append(new.run_id)
        check_invariants(new)
        return new

    def placeholders() -> dict[str, str]:
        mapping = {"$thread": conv.thread_id}
        for placeholder, run_id in zip(("$run", "$run2"), run_ids, strict=False):
            mapping[placeholder] = run_id
        return mapping

    conv = settle(engine.commands.begin_run(conv, config=config, **fixture.start))

    for step in fixture.steps:
        if isinstance(step, CommandStep):
            func = getattr(engine.commands, COMMANDS[step.name])
            kwargs = substitute(step.kwargs, placeholders())
            if step.name == "begin_run":
                kwargs.setdefault("config", config)
            conv = settle(func(conv, **kwargs))
            continue
        parsed = engine.parse_event(substitute(step.raw, placeholders()))
        if isinstance(parsed, Diagnostic):
            codes.append(str(parsed.code))
            continue
        conv = settle(engine.reduce(conv, parsed))

    return ReplayResult(conv=conv, diagnostic_codes=tuple(codes), run_ids=tuple(run_ids))


# --- expectations --------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: _jsonable(getattr(value, f.name))
            for f in dataclasses.fields(value)
            if not f.name.startswith("_")
        }
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(v) for v in value)
    return value


def view_of(result: ReplayResult) -> dict[str, Any]:
    """The JSON view that ``expect`` is matched against."""
    view: dict[str, Any] = _jsonable(result.conv)
    view["diagnostics"] = {"codes": list(result.diagnostic_codes)}
    return view


def _resolve(view: Any, path: str) -> Any:
    current = view
    for part in path.split("."):
        if part == "length" and isinstance(current, list):
            return len(current)
        if isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(path)
    return current


def match(actual: Any, expected: Any, path: str = "") -> list[str]:
    """Partial match: dicts match on the expected keys, lists element-wise and by length."""
    where = path or "<root>"
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{where}: expected an object, got {actual!r}"]
        problems: list[str] = []
        for key, value in expected.items():
            if key not in actual:
                problems.append(f"{where}.{key}: missing")
            else:
                problems.extend(match(actual[key], value, f"{path}.{key}" if path else key))
        return problems
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return [f"{where}: expected a list, got {actual!r}"]
        if len(actual) != len(expected):
            return [f"{where}: expected {len(expected)} items, got {len(actual)}"]
        problems = []
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            problems.extend(match(a, e, f"{path}.{i}"))
        return problems
    if actual != expected:
        return [f"{where}: expected {expected!r}, got {actual!r}"]
    return []


def check_expect(view: Mapping[str, Any], expect: Mapping[str, Any]) -> list[str]:
    """Match every dotted ``expect`` path against ``view``; return the mismatches."""
    problems: list[str] = []
    for path, expected in expect.items():
        try:
            actual = _resolve(view, path)
        except (KeyError, IndexError):
            problems.append(f"{path}: not found")
            continue
        problems.extend(match(actual, expected, path))
    return problems


def placeholders_of(result: ReplayResult) -> dict[str, str]:
    """The placeholder values a replay assigned (for use in ``expect``)."""
    mapping = {"$thread": result.conv.thread_id}
    mapping.update(zip(("$run", "$run2"), result.run_ids, strict=False))
    return mapping


def assert_fixture(fixture: Fixture, engine: Engine | None = None) -> ReplayResult:
    """Replay ``fixture`` and fail with every mismatch against its ``expect``."""
    result = replay(fixture, engine)
    expect = substitute(fixture.expect, placeholders_of(result))
    problems = check_expect(view_of(result), expect)
    assert not problems, f"{fixture.name} ({', '.join(fixture.reqs)}):\n  " + "\n  ".join(problems)
    return result


def fixture_ids(paths: Sequence[Path]) -> list[str]:
    """Test IDs: the fixture names."""
    return [p.stem for p in paths]
