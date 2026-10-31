# Tasks — reflex-agentkit v0.1

> Source specs: [Constitution v1.0](../constitution.md) · [PRD v1.1](../prd/agentkit-v0.1.md) ·
> [API v1.1](../api/agentkit-python-api-v1.md) · [TD v1.0](../technical/agentkit-architecture.md) ·
> [Data Model v1.0](../data-model/agentkit-schema.md) · [Plan v1.0](../plans/agentkit-phase-1.md)
> Plan phase covered: Phase 1 (WP0–WP8 → `v0.1.0`) · Generated: 2026-10-30 · Version 1.1 (Analyze fixes applied) · Status: `APPROVED` (2026-10-30)

## Conventions of this file

- **Order** is execution order inside each WP, except tasks marked **[P]**, which have no
  dependency on each other and touch no shared files.
- **Size:** v0.1 has 52 tasks, above the 8–25 the template treats as healthy. Each **WP
  section is therefore a sub-feature** (4–13 tasks) with its own review checkpoint.
  Execution goes in batches of 3–5 tasks. The batch stops at the end of a WP even if
  fewer than 3 tasks remain.
- **Status:** `[ ]` pending · `[~]` in progress · `[x] YYYY-MM-DD` done · `[!]` blocked (with a note).
- **Test-first (Art. 6):** tasks tagged **TF** write their failing tests first and commit
  them in the same PR before the implementation (the reviewer checks the order in the
  commit history: `test:` commit before `feat:`).
- **Test naming:** `test_REQ_<NNN>_<k>_<behavior>` (for example
  `test_REQ_013_3_approve_with_edited_args_records_payload`). Tests for TD/DM items use
  `test_DD_<NNN>_…` / `test_INV_<N>_…`. `uv run pytest -k REQ_013` selects a requirement.
- **Commands:** all through uv (Plan §1.1). "CI green" means every job in
  `.github/workflows/ci.yml` passes on the PR.
- **Spec drift rule:** if a task shows that a spec is wrong, **stop**, update the spec
  (in place, with a change-history row, while unreleased), and only then continue.
- **Commits:** Conventional Commits (`feat(core): …`, `test(core): …`, `ci: …`,
  `docs: …`), each ending with the attribution trailer required by the repo's agent
  configuration.

---

## WP0 — Foundation and CI

### T-001 · Project skeleton with uv `[x] 2026-10-31`
- **What:** `pyproject.toml` per Plan §1.2 (hatchling, `src/` layout, runtime deps and
  extras per TD DD-001, dependency groups, `[tool.uv] default-groups`, uv workspace with
  `examples/*`). Package skeleton per TD §5.1 with empty modules and `py.typed`.
  `__version__ = "0.1.0.dev0"` literal in `src/reflex_agentkit/__init__.py` (single source,
  read by `[tool.hatch.version]`). The top-level `__init__.py` already uses the lazy PEP 562
  `__getattr__` pattern for future Reflex-dependent exports (API §1). `.gitignore` additions (`.venv`, `.web`,
  `dist`, `.coverage`, `.idea`). Then `uv lock`.
- **REQ:** REQ-031.1 · DD-001
- **Files:** `pyproject.toml`, `uv.lock`, `src/reflex_agentkit/**/__init__.py`, `src/reflex_agentkit/py.typed`, `.gitignore`
- **Depends on:** —
- **Done:** `uv sync --locked --all-extras` succeeds on a clean clone.
  `uv run python -c "import reflex_agentkit, reflex_agentkit.core; print(reflex_agentkit.__version__)"` prints `0.1.0.dev0`.
  `uv build` creates a wheel and an sdist in `dist/`.

### T-002 · Lint, type and test configuration `[x] 2026-10-31`
- **What:**
  - `[tool.ruff]`: py311 target, line length 100; rules `E,F,W,I,UP,B,SIM,RUF,ASYNC,S`
    (with `S101` allowed in tests).
  - `[tool.mypy]`: `strict = true` for `reflex_agentkit.core.*` and
    `reflex_agentkit.state.*`, standard checks elsewhere. No `ignore_missing_imports`; the
    single `jsonpatch` import carries an inline `# type: ignore[import-untyped]` with its
    reason (TD DD-007, Art. 7).
  - `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, markers
    `slow`/`redis`/`bench`/`network`, `addopts = "-m 'not redis and not bench and not network'"`.
  - `[tool.coverage]`: `source = ["reflex_agentkit"]`, plus a per-package threshold
    script (`scripts/check_gated_coverage.py`) that fails if `reflex_agentkit/core` or
    `reflex_agentkit/state` is < 85 % (an empty package counts as 100 %).
  - A placeholder test `tests/test_smoke.py::test_package_imports`.
- **REQ:** Art. 6, Art. 7 · REQ-032.1
- **Files:** `pyproject.toml`, `scripts/check_gated_coverage.py`, `tests/test_smoke.py`, `tests/conftest.py`
- **Depends on:** T-001
- **Done:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and
  `uv run pytest` all pass. `uv run python scripts/check_gated_coverage.py` exits 0 on an
  empty core (100 % of nothing). A deliberately untyped function in `core` makes `mypy`
  fail; it is removed before merge.

### T-003 · CI workflow `[x] 2026-10-31` (PR #1: all 6 checks green)
- **What:** `.github/workflows/ci.yml` with `astral-sh/setup-uv` (cache on) and these
  jobs:
  - `lint`;
  - `typecheck`;
  - `test` (matrix 3.11/3.12/3.13: `uv sync --locked --all-extras --python ${{matrix.python}}` → `uv run pytest --cov` → coverage check);
  - `core-no-extras` (`uv sync --locked --no-dev --group test`, then a script that
    imports `reflex_agentkit.core` and asserts that `"reflex"`, `"pydantic_ai"`,
    `"langgraph"` and `"ag_ui_langgraph"` are not in `sys.modules`, then
    `uv run pytest tests/unit/core`).
  Triggers: PRs and pushes to `main`/`develop`.
- **REQ:** REQ-031.2, REQ-032.1 · Art. 1, 7
- **Files:** `.github/workflows/ci.yml`, `scripts/assert_core_isolated.py`
- **Depends on:** T-002
- **Done:** a PR shows all 6 checks green (lint, typecheck, test ×3, core-no-extras).

### T-004 · Upstream contract tests (protocol and Reflex) `[P]` `[x] 2026-10-31`
- **What:** tests that pin the facts verified in the TD:
  1. `ag_ui.core.EventType` has the 31 v1.0 values and no `THINKING_*`;
     `RunFinishedOutcome` discriminates `success`/`interrupt`/`cancelled`; `ResumeEntry`
     and `Interrupt` have the fields we use.
  2. Reflex: an unannotated subclass attribute of a mixin raises `VarTypeError`, while a
     `ClassVar` annotation does not create a var.
- **REQ:** TD §8.4 (1, 4) · DD-006 · REQ-026.1 (Reflex does not cancel background tasks on disconnect)
- **Files:** `tests/contract/test_agui_protocol.py`, `tests/contract/test_reflex_facts.py`
- **Depends on:** T-002
- **Done:** `uv run pytest tests/contract -q` passes. Each test docstring cites the TD
  section.

### T-005 · Repo hygiene and agent pointers `[P]` `[x] 2026-10-31`
- **What:**
  - `AGENTS.md`: points to `specs/constitution.md` and the standard commands.
  - `CLAUDE.md`: replace the "add commands once pyproject exists" note with Plan §1.1.
  - `CONTRIBUTING.md`: uv setup, test naming, Conventional Commits, delta-spec gate.
  - `CHANGELOG.md`: Keep a Changelog with `[Unreleased]`.
  - Fix the README title typo `reflex-agenkit` → `reflex-agentkit`.
- **REQ:** REQ-033.1 · Art. 9
- **Files:** `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `README.md`
- **Depends on:** T-001
- **Done:** `grep -c "specs/constitution.md" AGENTS.md CLAUDE.md` is ≥ 1 for each file.
  `grep -n "reflex-agenkit" README.md` returns nothing.

---

## WP1 — Pure core (test-first)

### T-006 · Errors, enums, JSON aliases, value types · TF `[x] 2026-10-31`
- **What:** `core/errors.py` (API §9.1 hierarchy; `ErrorCode` StrEnum, DM §6) and
  `core/models.py`:
  - `MessageRole`, `RunStatus`, `ToolCallStatus`, `DiagnosticCode`;
  - `JsonValue`/`JsonObject`;
  - frozen + slots dataclasses `ChatMessage`, `ToolCall`, `PendingInterrupt`,
    `OpenInterrupt`, `InterruptAnswer`, `ReasoningRecord`, `CustomEventRecord`,
    `Diagnostic`, `ReducerConfig` (DM §3);
  - the `TolerantPickle` mixin (DM §8).
- **REQ:** DM §2–3, §6, §8 · API §5, §9
- **Files:** `src/reflex_agentkit/core/{errors,models}.py`, `tests/unit/core/test_models.py`, `tests/unit/core/test_errors.py`
- **Depends on:** T-002
- **Done:**
  - Tests: StrEnum values serialize to strings via `json.dumps(dataclasses.asdict(...))`.
  - Pickle round-trips. The tolerant restore (`_from_state`, reached through
    `TolerantPickle.__reduce__`, DM §8 v1.2) tolerates a missing field (default) and an
    unknown field (dropped).
  - `ConfigurationError` is an instance of `ValueError`; `AdapterNotInstalledError` is
    an instance of `ImportError`.
  - `uv run mypy` is clean.

### T-007 · `ConversationState` aggregate · TF `[x] 2026-10-31`
- **What:**
  - `core/conversation.py`: `ConversationState` (DM §3.10) with the `with_(**changes)`
    helper that rebuilds the derived `_tool_index`/`_message_index` (excluded from
    `compare` and from pickling); `initial(config)`.
  - Test helper `tests/helpers/invariants.py::check_invariants(conv)` implementing
    INV-1…INV-11.
- **REQ:** DM §3.10, §4
- **Files:** `src/reflex_agentkit/core/conversation.py`, `tests/helpers/invariants.py`, `tests/unit/core/test_conversation.py`
- **Depends on:** T-006
- **Done:** `test_INV_2_indexes_follow_with_` passes. The tolerant pickle round-trip
  passes. `check_invariants` flags hand-built violations of each invariant (one negative
  test per INV).

### T-008 · Fixture loader and runner `[x] 2026-10-31`
- **What:** `tests/helpers/fixtures.py`, which:
  - parses the DM §10 JSONL format (header, placeholders `$thread`/`$run`/`$run2`,
    `$command` lines, AG-UI events validated with the `ag_ui.core` TypeAdapter for
    `Event`, invalid lines kept as raw dicts so REQ-012.3 can be exercised);
  - replays the fixture through `reduce` and the commands;
  - collects the diagnostic codes;
  - asserts the partial-match `expect`;
  - checks the invariants after every step.

  Also `tests/unit/core/test_fixtures.py`, which parametrizes over
  `tests/fixtures/events/*.jsonl`, with the test id = the fixture name and the header
  `reqs` attached to the report.
- **REQ:** REQ-005.3 · DM §10
- **Files:** `tests/helpers/fixtures.py`, `tests/unit/core/test_fixtures.py`, `tests/fixtures/events/.gitkeep`
- **Depends on:** T-007
- **Done:** the loader's own unit tests (placeholder substitution, partial match, command
  lines) pass. The parametrized test collects zero fixtures without error.

### T-009 · JSON Patch façade · TF `[P]` `[x] 2026-10-31`
- **What:** `core/_patch.py`: `apply_patch(doc: JsonObject, ops: list[JsonObject]) -> JsonObject`
  (deep copy, atomic, raises `PatchError` on any failure including a failed `test` op).
  This is the only `jsonpatch` importer, with one justified `type: ignore`.
- **REQ:** REQ-016.2, REQ-016.3 · DD-007
- **Files:** `src/reflex_agentkit/core/_patch.py`, `tests/unit/core/test_patch.py`
- **Depends on:** T-006
- **Done:** tests cover add/remove/replace/move/copy/test, a failing middle op leaves the
  input unchanged (atomicity), and a bad path raises `PatchError`. Grep shows
  `import jsonpatch` only in `_patch.py`.

### T-010 · Reducer: dispatch, lifecycle, steps, tolerated and unknown events · TF `[x] 2026-10-31`
- **What:**
  - `core/reducer.py`: `reduce()` with a dispatch table; the `RUN_STARTED` active-run
    check (`last_run_ids`) and the `STALE_RUN_EVENT` diagnostic; `STEP_*`; `RUN_ERROR`;
    `ACTIVITY_*`/`SUBAGENT_*`/`RAW` → `IGNORED_EVENT`; unknown types →
    `UNKNOWN_EVENT_TYPE`.
  - The validation helper `parse_event(raw) -> BaseEvent | Diagnostic` used by the
    clients.
  - Fixtures: `lifecycle_happy`, `run_error`, `stale_run_event`, `steps`,
    `ignored_families`, `unknown_type`, `invalid_event`.
  - *Pulled forward from T-015 (2026-10-31):* the basic `commands.begin_run` (user
    message, lazy `thread_id`, new `run_id`, `last_run_ids`, status `running`, error
    cleared). The T-008 runner starts every replay with it, so no fixture can run before
    it. T-015 completes it (interrupt bookkeeping, `abandoned_interrupt_ids`,
    `client_tool_rounds`) and adds the other commands.
- **REQ:** REQ-004.3, REQ-010.1–3, REQ-012.1–3, REQ-005.1
- **Files:** `src/reflex_agentkit/core/reducer.py`, `tests/fixtures/events/{lifecycle_happy,run_error,stale_run_event,steps,ignored_families,unknown_type,invalid_event}.jsonl`
- **Depends on:** T-008
- **Done:** `uv run pytest -k "REQ_004 or REQ_010 or REQ_012" -q` passes, and all 7
  fixtures pass.

### T-011 · Reducer: text messages · TF `[x] 2026-10-31`
- **What:** START/CONTENT/END/CHUNK, the implicit message on an unknown ID
  (`IMPLICIT_MESSAGE`), and the close of open messages on any terminal event.
- **REQ:** REQ-008.1–6
- **Files:** `core/reducer.py`, `tests/fixtures/events/{text_stream,text_chunks,text_unknown_id,text_unclosed_at_finish}.jsonl`
- **Depends on:** T-010
- **Done:** `uv run pytest -k REQ_008 -q` passes, and INV-5 holds after the terminal
  event in every fixture.

### T-012 · Reducer: tool calls · TF `[ ]`
- **What:**
  - START/ARGS/END/CHUNK/RESULT. Linking to the parent message. `dirty_tool_args`.
  - Invalid JSON at END → `error`. The 1 MiB cap → `ARGS_TOO_LARGE`.
  - Unknown IDs → `UNKNOWN_TOOL_CALL_ID`.
  - Client-tool marking (`is_client_tool` from `config`). A client tool stays `running`
    after END.
  - RESULT appends the `tool` message (deduplicated by `messageId`).
- **REQ:** REQ-009.1–7, REQ-018.2 (marking)
- **Files:** `core/reducer.py`, `tests/fixtures/events/{tool_call_happy_path,tool_call_chunks,tool_call_invalid_args,tool_call_unknown_id,tool_call_args_too_large,client_tool_marked}.jsonl`
- **Depends on:** T-010
- **Done:** `uv run pytest -k REQ_009 -q` passes. INV-3 holds.

### T-013 · Reducer: state, messages snapshot, CUSTOM, reasoning · TF `[ ]`
- **What:**
  - `STATE_SNAPSHOT`/`STATE_DELTA`, with a failed patch → stale + `PATCH_FAILED`.
  - `MESSAGES_SNAPSHOT` (DM §7.1), keeping the surviving tool calls.
  - The CUSTOM ring.
  - `REASONING_*` and `REASONING_ENCRYPTED_VALUE` → `ReasoningRecord`, with assistant
    linking.
- **REQ:** REQ-016.1–4, REQ-010.4–5, REQ-011.1–2
- **Files:** `core/reducer.py`, `tests/fixtures/events/{state_snapshot_delta,state_delta_fails,messages_snapshot,custom_ring,reasoning_stream,reasoning_encrypted}.jsonl`
- **Depends on:** T-009, T-011, T-012
- **Done:** `uv run pytest -k "REQ_016 or REQ_010_4 or REQ_010_5 or REQ_011" -q` passes.
  INV-9 holds on `custom_ring` with `custom_events_limit=3`.

### T-014 · Reducer: `RUN_FINISHED` outcomes · TF `[ ]`
- **What:**
  - success/absent → `idle`, unless client-tool calls await execution (`is_client_tool`
    calls in `running`, or `outcome.pending_tool_call_ids`), in which case `running` is
    kept (PRD REQ-004.1, DM §7.1). Fixture: `finish_with_pending_client_tool`.
  - interrupt → `OpenInterrupt`s. `reason == "tool_call"` + `tool_call_id` → the call
    goes to `pending_approval` with `interrupt_id`. Generic interrupts are queued in
    arrival order. Status → `awaiting_input`.
  - cancelled → `cancelled`.
- **REQ:** REQ-004.1–2, REQ-013.1, REQ-014.1, REQ-014.3 · API v1.1 §8.3
- **Files:** `core/reducer.py`, `tests/fixtures/events/{finish_success,finish_interrupt_tool_call,finish_interrupt_generic_multi,finish_mixed_interrupts,finish_cancelled_outcome}.jsonl` (the tool-call fixture uses the exact PydanticAI shape from TD DD-011)
- **Depends on:** T-012
- **Done:** `uv run pytest -k "REQ_004 or REQ_013_1 or REQ_014" -q` passes. INV-4 and
  INV-6 hold.

### T-015 · Commands · TF `[ ]`
- **What:** `core/commands.py`:
  - `begin_run(conv, *, user_text=None, resume=False, config)`: new `run_id`, lazy
    `thread_id`, `last_run_ids`, clears error, consumes `abandoned_interrupt_ids`;
  - `apply_approval(conv, call_id, edited_args)` (validates JSON object and the 64 KiB
    cap);
  - `apply_rejection`;
  - `apply_interrupt_response`;
  - `apply_cancel(conv)` (the running variant; and the paused variant, which moves the
    non-local interrupt IDs to `abandoned_interrupt_ids` and clears `interrupts` and
    `answers`, DM §3.10);
  - `apply_client_tool_result`;
  - `all_answered`;
  - `resume_entries` (excludes local interrupts; includes cancelled ones);
  - `new_thread(conv)`.
  Every function is pure and returns `ConversationState`.
- **REQ:** REQ-001.1–3, REQ-002.1–4, REQ-007.4, REQ-013.2–7, REQ-014.2–4, REQ-015.1–3, REQ-018.2–3
- **Files:** `src/reflex_agentkit/core/commands.py`, `tests/unit/core/test_commands.py`, `tests/fixtures/events/{hitl_approve,hitl_approve_edited,hitl_reject,hitl_generic_queue,hitl_cancel_while_paused}.jsonl`
- **Depends on:** T-014
- **Done:** `uv run pytest -k "REQ_001 or REQ_002 or REQ_013 or REQ_014 or REQ_015" -q`
  passes. `resume_entries` output for `hitl_approve_edited` equals
  `[ResumeEntry(interrupt_id="int-c1", status="resolved", payload={"approved": True, "editedArgs": {...}})]`.

### T-017 · Client tools · TF `[P]` `[ ]`
- **What:**
  - `core/tools.py`: the `client_tool` decorator (name, description from the docstring,
    parameters JSON Schema via pydantic `TypeAdapter`/`create_model` from the hints;
    `ConfigurationError` on missing or unsupported hints).
  - The frozen `ClientTool` with `to_agui_tool()`.
  - `invoke(args, timeout_s)`: async direct, sync via `asyncio.to_thread`;
    `asyncio.timeout`; returns `(ok: bool, text: str)` with JSON encoding for non-str
    results and `""` for `None`.
- **REQ:** REQ-018.1, REQ-018.4–5, REQ-024.2 · API §6
- **Files:** `src/reflex_agentkit/core/tools.py`, `tests/unit/core/test_tools.py`
- **Depends on:** T-006
- **Done:** `uv run pytest -k "REQ_018 or REQ_024_2" -q` passes. This includes a sync
  handler that sleeps 0.3 s while the event loop keeps ticking (a concurrent counter
  advances).

### T-016 · `RunInputBuilder` · TF `[ ]`
- **What:** `core/run_input.py`: the DM §7.3 egress (user, system and developer
  messages, reasoning with encrypted value placed before its assistant message,
  assistant tool calls with edited args, tool messages with error), plus `state`, `tools`
  (`ClientTool.to_agui_tool()`), `resume`, `protocol_version="1.0"`.
- **REQ:** REQ-001.2, REQ-011.2, REQ-016.7, REQ-018.1 · API §8.1
- **Files:** `src/reflex_agentkit/core/run_input.py`, `tests/unit/core/test_run_input.py`
- **Depends on:** T-015, T-017
- **Done:**
  - `test_REQ_011_2_encrypted_reasoning_resent` passes.
  - The round-trip property `ingress(MESSAGES_SNAPSHOT(egress(conv))) ≅ conv.messages`
    passes for the fixtures' final states.
  - The output validates as `ag_ui.core.RunAgentInput`.

### T-018 · Reducer property tests · TF `[ ]`
- **What:** Hypothesis strategies that generate plausible-but-chaotic AG-UI event
  sequences (valid events with random IDs drawn from small pools, so collisions and
  out-of-order events are frequent) interleaved with commands. Properties:
  - totality (no exception);
  - determinism (same seed → equal states);
  - INV-1…INV-12 after every step;
  - no input mutation.
- **REQ:** REQ-005.1–2 · DM §4
- **Files:** `tests/unit/core/test_reducer_properties.py`, `tests/helpers/strategies.py`
- **Depends on:** T-015
- **Done:** `uv run pytest tests/unit/core/test_reducer_properties.py -q` passes with
  `max_examples=500` per property in < 10 s locally. Coverage of `core` ≥ 85 %
  (`scripts/check_gated_coverage.py`).

---

## WP2 — Clients

### T-019 · Client protocols · TF `[ ]`
- **What:** `core/clients/base.py`: the `AGUIAgent` and `AgentClient` `Protocol`s
  (runtime-checkable) and `AgentSource`. Validated event decoding (`parse_event` reuse)
  with skip-and-warn.
- **REQ:** REQ-021.1, REQ-012.3 · API §7.1–7.2
- **Files:** `src/reflex_agentkit/core/clients/base.py`, `tests/unit/core/clients/test_base.py`
- **Depends on:** T-010
- **Done:** `isinstance(obj, AGUIAgent)` is true for a class that defines `run`.
  `uv run pytest -k REQ_021_1 -q` passes.

### T-020 · SSE parser · TF `[P]` `[ ]`
- **What:** `core/clients/sse.py`: an incremental parser over byte or str chunks
  (multi-line `data:`, `event:`/`id:` ignored, comments, CRLF/LF, a frame split across
  chunks, a trailing frame without a blank line at EOF is discarded).
- **REQ:** REQ-021.2
- **Files:** `src/reflex_agentkit/core/clients/sse.py`, `tests/unit/core/clients/test_sse.py`
- **Depends on:** T-006
- **Done:** `uv run pytest tests/unit/core/clients/test_sse.py -q` passes, with ≥ 8
  framing cases.

### T-021 · Fake AG-UI SSE server fixture `[P]` `[ ]`
- **What:** a pytest fixture `fake_agui_server(script)` that starts a Starlette app under
  `uvicorn` on an ephemeral port in a background thread. A script is a list of steps:
  `send(event)`, `sleep(s)`, `status(code)`, `content_type(ct)`, `close()`, `hang()`. The
  fixture records the received request bodies and headers and a
  `disconnected: threading.Event`.
- **REQ:** TD DD-010 (supports REQ-007.2, REQ-021)
- **Files:** `tests/helpers/fake_server.py`, `tests/integration/test_fake_server.py`
- **Depends on:** T-002
- **Done:** a self-test streams 3 events and observes the disconnect when the client
  closes early.

### T-022 · `HttpAGUIClient` · TF `[ ]`
- **What:** `core/clients/http.py`, as in API §7.3/§8:
  - camelCase JSON body;
  - static or callable headers;
  - `httpx.AsyncClient` (owned or injected);
  - status, content-type and read-timeout handling → `AgentHTTPError`/`AgentStreamError`;
  - EOF before a terminal event → `AgentStreamError`;
  - `aclose()` is idempotent;
  - no headers in any exception message or log record.
- **REQ:** REQ-021.2–4, REQ-021.6, REQ-007.2, REQ-004.4
- **Files:** `src/reflex_agentkit/core/clients/http.py`, `tests/integration/test_http_client.py`
- **Depends on:** T-019, T-020, T-021
- **Done:**
  - `uv run pytest -k "REQ_021 or REQ_007_2 or REQ_004_4" -q` passes.
  - `test_REQ_007_2_cancel_closes_upstream` asserts `server.disconnected.wait(1.0)`.
  - `test_REQ_021_6_headers_never_leak` checks `caplog` and the exception strings for
    the header value.

### T-023 · `InProcessAGUIClient` · TF `[P]` `[ ]`
- **What:** `core/clients/in_process.py`: wraps an `AGUIAgent`, validates the yielded
  events, propagates cancellation (the agent sees `CancelledError`), and maps agent
  exceptions to `AgentStreamError(reason="agent_raised")` with the original as
  `__cause__`. The driver (T-026) maps that reason to `ErrorCode.AGENT_EXCEPTION`.
- **REQ:** REQ-021.5, REQ-007.3
- **Files:** `src/reflex_agentkit/core/clients/in_process.py`, `tests/unit/core/clients/test_in_process.py`
- **Depends on:** T-019
- **Done:** `uv run pytest -k "REQ_021_5 or REQ_007_3" -q` passes.

---

## WP3 — Reflex state engine

### T-024 · Spike: Reflex in-process state testing (TD OQ-1) `[ ]`
- **What:** a timeboxed spike (≤ 0.5 d) to find how to instantiate an `rx.State` subclass
  and invoke foreground and background handlers in tests without a browser in reflex
  0.10.1. Candidates: Reflex testing helpers, `StateManagerMemory` + the app event
  processor, or `AppHarness` for smoke only. Record the decision in TD §11 (OQ-1 →
  resolved).
- **REQ:** — (enables REQ-001…004, 013…017 tests) · TD OQ-1
- **Files:** `specs/technical/agentkit-architecture.md` (§11 update), `tests/helpers/reflex_harness.py`
- **Depends on:** T-003
- **Done:** `tests/helpers/reflex_harness.py` has a working example test that invokes a
  background handler which does `async with self` twice and asserts that the state
  changed. TD §11 is updated in the same PR.

### T-025 · `StateAccess` port, fake and `RunRegistry` `[ ]`
- **What:**
  - `state/_driver.py` protocol `StateAccess`: `locked()` async context manager →
    `StateView(conv, cancel_requested, publish(conv), client_token)`.
  - `tests/helpers/fake_state_access.py`, which counts publishes and records the
    projected snapshots.
  - `state/_registry.py` `RunRegistry`: register, unregister, cancel by
    `(token, run_id)`, process-local.
- **REQ:** TD §5.2, DD-004 (supports REQ-007)
- **Files:** `src/reflex_agentkit/state/{_driver,_registry}.py`, `tests/helpers/fake_state_access.py`, `tests/unit/state/test_registry.py`
- **Depends on:** T-007
- **Done:** the registry tests pass (register → cancel returns True and cancels the
  task; a miss returns False).

### T-026 · `RunDriver`: streaming, batching, ownership · TF `[ ]`
- **What:**
  - The driver loop per TD Flow A: pump task + bounded queue (DD-003), flush-on-deadline
    (DD-005; `flush_interval_ms=0` flushes every event), terminal flush.
  - The ownership check on every flush.
  - Diagnostics logged via `_log.py` with `thread_id`/`run_id`, then cleared.
  - Failure mapping per TD Flow E.
  - An `on_flush(custom_events_since_last)` callback for the hook.
- **REQ:** REQ-006.1–4, REQ-004.3–4, REQ-026.2, REQ-027.1–2, REQ-021.3–4 (mapping)
- **Files:** `src/reflex_agentkit/state/_driver.py`, `src/reflex_agentkit/core/_log.py`, `tests/unit/state/test_driver_streaming.py`
- **Depends on:** T-025, T-022, T-023
- **Done:**
  - `test_REQ_006_3_push_rate_bounded`: 1,000 deltas in 1 s with 50 ms → ≤ 25 publishes.
  - `test_REQ_026_2_ownership_lost_stops_and_closes_upstream` passes.
  - `test_REQ_027_2_no_content_above_debug`: no message text in records ≥ INFO.

### T-027 · `RunDriver`: cancellation · TF `[ ]`
- **What:** TD Flow D: the registry path (immediate cancel; `finally` closes the pump and
  the client; final flush with `apply_cancel`) and the flag path (`cancel_requested`
  observed at the next tick ≤ `max(flush_interval, 100 ms)`, even with a silent
  upstream). Queued events are discarded.
- **REQ:** REQ-007.1, REQ-007.4–5
- **Files:** `state/_driver.py`, `tests/unit/state/test_driver_cancel.py`
- **Depends on:** T-026
- **Done:** `uv run pytest -k "REQ_007" tests/unit/state -q` passes, including
  `test_REQ_007_1_flag_path_with_silent_upstream_under_1s`.

### T-028 · `RunDriver`: client-tool rounds · TF `[ ]`
- **What:** TD Flow B and Flow C.4:
  - after `RUN_FINISHED`, run the client tools that are `running`, concurrently, outside
    the lock;
  - approval-required tools → local `OpenInterrupt` + `pending_approval`, then end the
    task;
  - follow-up run in the same task; `client_tool_rounds` and `max_client_tool_rounds`
    → `CLIENT_TOOL_LOOP_LIMIT`;
  - handler errors and timeouts → tool `error`, and the conversation continues.
- **REQ:** REQ-018.2–5 · DD-009
- **Files:** `state/_driver.py`, `tests/unit/state/test_driver_client_tools.py`
- **Depends on:** T-026, T-017, T-016
- **Done:** `uv run pytest -k "REQ_018 or DD_009" tests/unit/state -q` passes.

### T-029 · `AgentState` mixin: configuration, vars, projection · TF `[ ]`
- **What:** `state/agent_state.py`:
  - `AgentState(rx.State, mixin=True)` with the ClassVars of API §4.1 (incl.
    `max_client_tool_rounds`);
  - `__init_subclass__` validation → `ConfigurationError`;
  - the public vars and computed vars (§4.2);
  - backend vars `_conv`, `_cancel_requested`, `_pending_start`;
  - `state/_projection.py` (DM §7.2; parses `dirty_tool_args`);
  - the `StateAccess` implementation over `async with self`.
- **REQ:** API §4.1–4.2 · REQ-003.1, REQ-025.1 · DD-006, DD-008
- **Files:** `src/reflex_agentkit/state/{agent_state,_projection}.py`, `tests/unit/state/test_agent_state_config.py`, `tests/unit/state/test_projection.py`
- **Depends on:** T-024, T-026
- **Done:**
  - Tests: a missing `agent` → `ConfigurationError` at class definition; negative
    `flush_interval_ms` → error; a duplicate client-tool name → error.
  - The projection never contains `encrypted_value` (INV-11).
  - `test_REQ_003_1_states_isolated_per_token` (two tokens, one run each) passes.

### T-030 · `AgentState` handlers and hooks · TF `[ ]`
- **What:** the handlers of API §4.3 with their preconditions and no-op rules:
  - `send_message`, `approve_tool` (`str` JSON accepted), `reject_tool`,
    `respond_to_interrupt`, `cancel_run`, `new_thread`, `set_shared_state`,
    `patch_shared_state` (with `shared_state_model` validation), `retry_run`;
  - the `_drive_run` background handler with no arguments and the `_pending_start`
    claim;
  - hooks `create_client`, `prepare_run_input`, `on_custom_event` (exceptions logged),
    `on_run_end`;
  - the 64 KiB payload caps.
- **REQ:** REQ-001.1–6, REQ-002, REQ-007.1, REQ-013.2–7, REQ-014.2–4, REQ-015, REQ-016.5–6, REQ-017, REQ-020, REQ-028 · TD §6.1
- **Files:** `state/agent_state.py`, `tests/unit/state/test_agent_state_handlers.py`
- **Depends on:** T-029, T-027, T-028
- **Done:**
  - `uv run pytest -k "REQ_001 or REQ_002 or REQ_013 or REQ_014 or REQ_015 or REQ_017 or REQ_020" tests/unit/state -q`
    passes.
  - `test_TD_6_1_forged_drive_run_is_noop` passes.

### T-031 · Cross-cutting state tests: secret leak, responsiveness, multi-worker cancel `[ ]`
- **What:**
  1. **REQ-025.2:** a configured state with `HttpAGUIClient(headers={"Authorization": "Bearer SECRET-123"})`
     runs against the fake server; the client-visible state, serialized with Reflex's
     `json_dumps`, must contain no `SECRET-123`.
  2. **REQ-024.1:** an agent with 2 s of offloaded work runs; a second token's simple
     handler completes in < 200 ms.
  3. **REQ-007.6:** two `StateManagerRedis` instances against a Redis container
     (`redis` marker). `cancel_run` goes through instance B and the driver runs on
     instance A → `cancelled` in < 1 s. Add a CI job `redis` with a `services: redis`
     container.
  4. **REQ-003.2:** two tokens stream concurrently from the same agent; each token's
     state receives only its own run's messages (`test_REQ_003_2_concurrent_clients_isolated`).
- **REQ:** REQ-025.2, REQ-024.1, REQ-007.6, REQ-003.2
- **Files:** `tests/integration/test_secret_hygiene.py`, `tests/integration/test_responsiveness.py`, `tests/integration/test_multiworker_cancel.py`, `.github/workflows/ci.yml`
- **Depends on:** T-030
- **Done:** `uv run pytest tests/integration -q` and `uv run pytest -m redis -q` (locally
  with `docker run -p 6379:6379 redis:7`) pass. The CI `redis` job is green. The PRD
  REQ-007.6 priority is changed to MUST, with a change-history row.

---

## WP4 — PydanticAI adapter

### T-032 · Adapter import guard `[P]` `[ ]`
- **What:** `adapters/_require.py::require(extra, module)`, which raises
  `AdapterNotInstalledError` with the exact API §7.7 message. Both adapter modules call it
  at import.
- **REQ:** REQ-031.3
- **Files:** `src/reflex_agentkit/adapters/_require.py`, `tests/unit/adapters/test_require.py`
- **Depends on:** T-006
- **Done:** a test that monkeypatches `sys.modules["pydantic_ai"] = None` asserts the
  error type and message.

### T-033 · `PydanticAIAgent` · TF `[ ]`
- **What:** `adapters/pydantic_ai.py`, per API §7.5 / TD DD-011: `run()` →
  `AGUIAdapter(agent, run_input).run_stream(output_type=…injected…, deps=…, **run_kwargs)`;
  `deps` and `deps_factory` are mutually exclusive.
- **REQ:** REQ-022.1, REQ-022.4
- **Files:** `src/reflex_agentkit/adapters/pydantic_ai.py`, `tests/unit/adapters/test_pydantic_ai_unit.py`
- **Depends on:** T-019, T-032
- **Done:** `uv run pytest -k "REQ_022_1 or REQ_022_4" -q` passes, including
  `test_REQ_022_4_injects_deferred_requests` (an agent declared with plain `str` output and a
  `requires_approval` tool ends its run with an interrupt outcome). With `TestModel` and a text reply, the
  events stream starts with `RUN_STARTED` and ends with `RUN_FINISHED`.

### T-034 · PydanticAI integration: approvals and client tools `[ ]`
- **What:** end-to-end through `InProcessAGUIClient` + reducer + commands +
  `RunInputBuilder` with `TestModel(call_tools=[...])`:
  - approve (the tool runs);
  - approve with `editedArgs` (the tool receives the edited args; asserted inside the
    tool);
  - reject (the tool does not run; the model sees the rejection);
  - a client tool declared in `RunAgentInput.tools` is called and its result is fed back.
- **REQ:** REQ-022.2–3, REQ-013.5, REQ-018.2
- **Files:** `tests/integration/test_pydantic_ai_hitl.py`
- **Depends on:** T-033, T-016, T-015
- **Done:** `uv run pytest -k "REQ_022 or REQ_013_5" tests/integration -q` passes with no
  network.

### T-035 · PydanticAI contract test and fixture recorder `[ ]`
- **What:** contract test TD §8.4 item 2 (including the frontend-tool → `outcome=success` fact, Analyze A-18). `scripts/record_fixture.py --adapter pydantic-ai --scenario <name>`
  writes DM §10 JSONL from a `TestModel` run. Record and commit
  `pydantic_ai_approval_recorded.jsonl`.
- **REQ:** TD §8.4 (2) · DM §10 · REQ-005.3
- **Files:** `tests/contract/test_pydantic_ai_facts.py`, `scripts/record_fixture.py`, `tests/fixtures/events/pydantic_ai_approval_recorded.jsonl`
- **Depends on:** T-034
- **Done:** `uv run pytest tests/contract -q` passes, and the recorded fixture passes the
  fixture runner.

---

## WP5 — Components and quickstart

### T-036 · `message_list` and `composer` `[ ]`
- **What:** `components/messages.py`, `components/composer.py`, per API §10 / PRD
  REQ-023.2–3:
  - markdown without raw HTML (resolve TD OQ-3 and update TD §11);
  - streaming indicator;
  - Enter submits, Shift+Enter adds a newline;
  - disabled unless `can_send`.
- **REQ:** REQ-023.2–3, REQ-023.9 · DD-015
- **Files:** `src/reflex_agentkit/components/{messages,composer}.py`, `tests/unit/components/test_messages.py`, `tests/unit/components/test_composer.py`
- **Depends on:** T-029
- **Done:** render-to-string tests pass. `test_DD_015_raw_html_not_rendered` shows that
  `<img src=x onerror=alert(1)>` is escaped. The aria-labels are present.

### T-037 · `tool_call_card` with renderer dispatch, and `run_status_bar` `[P]` `[ ]`
- **What:** `components/tools.py` (header with name and status badge; collapsible args
  and result; `body` override; `rx.match` over the `tool_renderers` names; no
  `rx.match` when the mapping is empty) and `components/status.py` (status, step, cancel
  button while running, error).
- **REQ:** REQ-019.1–3, REQ-023.4, REQ-023.6 · DD-013
- **Files:** `src/reflex_agentkit/components/{tools,status}.py`, `tests/unit/components/test_tools.py`, `tests/unit/components/test_status.py`
- **Depends on:** T-029
- **Done:** `uv run pytest -k "REQ_019 or REQ_023_4 or REQ_023_6" -q` passes.

### T-038 · `approval_dialog` and `shared_state_panel` `[P]` `[ ]`
- **What:** `components/approval.py`:
  - open while `pending_approvals` is non-empty or `pending_interrupt` is set; one item
    at a time, approvals first;
  - approve, edit args (JSON text area validated client-side through the
    `approve_tool(call_id, str)` path), reject with an optional reason;
  - generic interrupt: `interrupt_renderers[reason]`, or a default message + JSON editor.

  `components/shared_state.py`: formatted JSON and the stale marker.
- **REQ:** REQ-023.5, REQ-023.7, REQ-014.3
- **Files:** `src/reflex_agentkit/components/{approval,shared_state}.py`, `tests/unit/components/test_approval.py`, `tests/unit/components/test_shared_state.py`
- **Depends on:** T-029
- **Done:** `uv run pytest -k "REQ_023_5 or REQ_023_7" -q` passes.

### T-039 · `agent_chat` composition and accessibility pass `[ ]`
- **What:** `components/chat.py`, the `agent_chat(state, *, tool_renderers, interrupt_renderers, show_shared_state, placeholder, **props)`
  composition. Public re-exports in `components/__init__.py` and in the top-level
  `reflex_agentkit/__init__.py` (`__all__` exactly as API §3).
- **REQ:** REQ-023.1, REQ-023.8–9 · API §3
- **Files:** `src/reflex_agentkit/components/{chat,__init__}.py`, `src/reflex_agentkit/__init__.py`, `tests/unit/test_public_api.py`
- **Depends on:** T-036, T-037, T-038
- **Done:** `test_public_api.py` asserts that each module's `__all__` equals the API §3
  table, and that `import reflex_agentkit.core` in a fresh interpreter leaves `"reflex"`
  out of `sys.modules` (lazy re-exports, API §1). An a11y test asserts that every button and input in a rendered `agent_chat` has
  an aria-label or text.

### T-040 · Quickstart example, smoke compile and gates `[ ]`
- **What:**
  - `examples/quickstart/` as a uv workspace member: `pyproject.toml`, `rxconfig.py`,
    `quickstart/quickstart.py` = API §2 verbatim.
  - Resolve TD OQ-2 (the compile command in CI) and update TD §11.
  - Tests:
    - `test_REQ_029_1_quickstart_line_count` (≤ 30 counted lines);
    - `test_REQ_029_3_readme_matches_quickstart`;
    - smoke compile with `AGENTKIT_MODEL=test` (the example swaps in `TestModel` through
      a 1-line env check *outside* the counted file: `rxconfig.py` or a conftest
      monkeypatch; the quickstart file stays verbatim).
  - CI job `examples-smoke`.
- **REQ:** REQ-029.1–3, REQ-030.2
- **Files:** `examples/quickstart/**`, `README.md` (quickstart block), `tests/smoke/test_quickstart.py`, `.github/workflows/ci.yml`
- **Depends on:** T-039, T-033
- **Done:** `uv run pytest tests/smoke -q` passes and the CI `examples-smoke` job is
  green. A manual check, `ANTHROPIC_API_KEY=… uv run --package quickstart reflex run`,
  streams, shows `get_weather`, and opens the approval dialog for `book_hotel`.

### T-041 · Release workflow and `0.1.0a1` on TestPyPI `[ ]`
- **What:** `.github/workflows/release.yml`:
  - on tag `v*`: `uv build` → `uv publish --trusted-publishing always`;
  - `a`/`rc` tags go to the `testpypi` environment
    (`--publish-url https://test.pypi.org/legacy/`); final tags go to `pypi` (environment
    with required reviewers).

  Bump to `0.1.0a1`, add a CHANGELOG entry, tag. Then the fresh-env walkthrough from Plan
  WP5 "Done", with the explicit TestPyPI index.
- **REQ:** REQ-032.2 · PRD §4.2
- **Files:** `.github/workflows/release.yml`, `src/reflex_agentkit/__init__.py`, `CHANGELOG.md`
- **Depends on:** T-040 · **Prerequisite:** the pending trusted publishers registered (Plan §2)
- **Done:** `0.1.0a1` is visible on test.pypi.org. The walkthrough takes < 5 min from an
  empty dir to a working chat (timed, noted in the execution log).

---

## WP6 — LangGraph adapter

### T-042 · `LangGraphAGUIAgent` · TF `[ ]`
- **What:** `adapters/langgraph.py`: a subclass of `ag_ui_langgraph.LangGraphAgent` with
  `emit_interrupt_outcome=True`, `enable_legacy_on_interrupt_event=False` and
  `emit_raw_events=False`. Checkpointer check → `ConfigurationError`. `run()` satisfies
  `AGUIAgent`.
- **REQ:** REQ-034.1, REQ-034.4
- **Files:** `src/reflex_agentkit/adapters/langgraph.py`, `tests/unit/adapters/test_langgraph_unit.py`
- **Depends on:** T-019, T-032
- **Done:** `uv run pytest -k "REQ_034_1 or REQ_034_4" -q` passes.

### T-043 · `request_tool_approval` and native multi-resume · TF `[ ]`
- **What:** `ApprovalDecision` and `request_tool_approval()` (the interrupt value with the
  native keys, TD DD-012). Override `_build_command_from_agui_resume`: single resolved →
  `Command(resume=payload)`; multiple → `Command(resume={interrupt_id: payload})`;
  cancelled tool approval → `{"approved": False, "reason": "cancelled"}`; cancelled
  generic → the upstream sentinel.
- **REQ:** REQ-034.2–3 · DD-012
- **Files:** `adapters/langgraph.py`, `tests/unit/adapters/test_langgraph_resume.py`
- **Depends on:** T-042
- **Done:** unit tests for the four resume shapes pass.

### T-044 · LangGraph integration: interrupts and approvals `[ ]`
- **What:** a scripted graph (`StateGraph` + `MemorySaver` + a fake chat model that emits
  a tool call) through `InProcessAGUIClient`:
  - a generic `interrupt()` answered with `respond_to_interrupt`;
  - an approval with edits (the tool node receives the edited args);
  - two simultaneous interrupts (each node gets its own answer);
  - a cancel while paused.
- **REQ:** REQ-034.2–3, REQ-014, REQ-015.3
- **Files:** `tests/integration/test_langgraph_hitl.py`
- **Depends on:** T-043, T-016, T-015
- **Done:** `uv run pytest -k REQ_034 tests/integration -q` passes with no network.

### T-045 · LangGraph contract test, legacy mode, upstream bug report `[P]` `[ ]`
- **What:**
  - Contract test TD §8.4 item 3 (`lg_interrupt_to_agui` key mapping; the override hook
    is invoked).
  - `legacy_interrupts=True` mode (REQ-034.5, SHOULD) with a unit test.
  - Draft the upstream issue text for the `fastapi` import (TD OQ-4) in
    `docs/integrations/upstream-issues.md`. The maintainer files it.
- **REQ:** TD §8.4 (3) · REQ-034.5 · TD OQ-4
- **Files:** `tests/contract/test_langgraph_facts.py`, `adapters/langgraph.py`, `docs/integrations/upstream-issues.md`
- **Depends on:** T-044
- **Done:** `uv run pytest tests/contract -q` passes. The issue draft exists.

---

## WP7 — Dojo examples

### T-046 · Shared model selection for examples `[ ]`
- **What:** `examples/_shared/models.py` (a workspace-local helper package). For
  `AGENTKIT_MODEL`:
  - unset → `anthropic:claude-sonnet-5-5`;
  - `ollama:<model>` → PydanticAI's OpenAI-compatible provider pointed at
    `OLLAMA_BASE_URL` (default `http://localhost:11434/v1`), and the LangGraph
    equivalent;
  - `test` → `TestModel` / a fake chat model.

  Document it in each example's README.
- **REQ:** REQ-030.2 · user decision (Claude default, Ollama option)
- **Files:** `examples/_shared/**`
- **Depends on:** T-040
- **Done:** unit tests cover the three branches without network.

### T-047 · `examples/pydantic_ai_dojo` (5 demos) `[ ]`
- **What:** a multi-page Reflex app, one page per demo (agentic chat, backend tool
  rendering with a `tool_renderers` weather card, human-in-the-loop, shared state with
  `shared_state_model` + panel, tool-based generative UI with a client tool + renderer),
  each 50–200 lines. Smoke compile test.
- **REQ:** REQ-030.1–2
- **Files:** `examples/pydantic_ai_dojo/**`, `tests/smoke/test_dojo_pydantic_ai.py`
- **Depends on:** T-046, T-034
- **Done:** smoke compile passes in CI. A line-count test enforces 50–200 per demo
  module. A manual run with Claude works, and with `AGENTKIT_MODEL=ollama:<model>` too
  (noted in the log).

### T-048 · `examples/langgraph_dojo` (5 demos) `[ ]`
- **What:** the same five demos with LangGraph graphs (approval via
  `request_tool_approval`; generic interrupt via `interrupt()`).
- **REQ:** REQ-030.1–2
- **Files:** `examples/langgraph_dojo/**`, `tests/smoke/test_dojo_langgraph.py`
- **Depends on:** T-046, T-044
- **Done:** the same as T-047.

---

## WP8 — Hardening, docs, release

### T-049 · Security review and benchmarks `[ ]`
- **What:**
  - Run `/security-review` on the branch and walk TD §6.1 vector by vector, adding a
    test per vector where one is missing (payload caps, forged trigger, XSS, header
    hygiene).
  - Benchmarks under the `bench` marker: NFR-01 (reducer p95 < 1 ms on 500 messages ×
    10k deltas) and NFR-04 (20 clients, flush lag p95 < 250 ms).
  - Weekly `deps-latest` workflow (`uv lock --upgrade` in a temporary copy, then tests;
    `continue-on-error`; opens an issue on failure).
- **REQ:** Art. 3 · TD §6 · NFR-01, NFR-04 · DD-001
- **Files:** `tests/bench/**`, `tests/integration/test_security_vectors.py`, `.github/workflows/deps-latest.yml`
- **Depends on:** T-041
- **Done:** `uv run pytest -m bench -q` meets the targets (or the DM §5 escape hatch is
  applied and recorded). There are no high or critical findings open.

### T-050 · Documentation site `[ ]`
- **What:** MkDocs Material: getting started (uv and pip), concepts (runs, threads,
  interrupts, shared state), the API reference (mkdocstrings is **not** added; reference
  pages are hand-written from the API Spec to avoid a new dependency), the sidecar
  guide, the security model ("what reaches the browser"), the Ollama guide, and
  troubleshooting (ClassVar `VarTypeError`, the PydanticAI banner). Final README:
  narrative, the test-locked quickstart, the feature table, the comparison table.
- **REQ:** REQ-033.1, REQ-033.3
- **Files:** `mkdocs.yml`, `docs/**` (excluding `docs/integrations/`, owned by T-051), `README.md`
- **Depends on:** T-047, T-048
- **Done:** `uv run mkdocs build --strict` passes. The README quickstart test still
  passes.

### T-051 · Upstream integration drafts `[P]` `[ ]`
- **What:** `docs/integrations/`: an AG-UI integrations-table entry (Python/Reflex
  client), a PydanticAI "UI with Reflex" page, a LangGraph "frontend with Reflex" page,
  each in the target repo's format, with links to the examples.
- **REQ:** REQ-033.2
- **Files:** `docs/integrations/{ag-ui-integration-entry,pydantic-ai-ui-with-reflex,langgraph-frontend-with-reflex}.md`
- **Depends on:** T-047, T-048
- **Done:** three drafts exist, each with a "how to submit" header (target repo, path,
  PR title).

### T-052 · `0.1.0rc1` → `v0.1.0` `[ ]`
- **What:** bump to `0.1.0rc1` → TestPyPI → fresh-env walkthrough (the PydanticAI and
  LangGraph dojos plus the quickstart) → fix anything found → CHANGELOG `[0.1.0]` → bump
  to `0.1.0` → tag `v0.1.0` → approve the `pypi` environment → verify
  `uv add reflex-agentkit` from PyPI.
- **REQ:** REQ-032.2 · PRD §4.1
- **Files:** `src/reflex_agentkit/__init__.py`, `CHANGELOG.md`
- **Depends on:** T-049, T-050, T-051
- **Done:** `reflex-agentkit 0.1.0` is on pypi.org. A clean `uv add` + quickstart works.
  All specs are marked with their released state.

---

## Traceability matrix

MUST requirements: every one has ≥ 1 task and ≥ 1 test, cited by name prefix
`test_REQ_<NNN>`.

| REQ | Priority | Tasks | Test location(s) |
|---|---|---|---|
| 001 | MUST | T-015, T-016, T-030 | unit/core/test_commands, unit/state/test_agent_state_handlers |
| 002 | MUST | T-015, T-030 | same |
| 003 | MUST | T-029, T-031 | unit/state/test_agent_state_config, integration (concurrent clients) |
| 004 | MUST | T-010, T-014, T-022, T-026 | fixtures, integration/test_http_client, unit/state/test_driver_streaming |
| 005 | MUST | T-008, T-010, T-018, T-035 | unit/core/test_fixtures, test_reducer_properties |
| 006 | MUST | T-026 | unit/state/test_driver_streaming |
| 007 | MUST (007.6 SHOULD → MUST at T-031) | T-015, T-022, T-023, T-027, T-030, T-031 | integration/test_http_client, unit/state/test_driver_cancel, integration/test_multiworker_cancel |
| 008 | MUST | T-011 | fixtures text_* |
| 009 | MUST | T-012 | fixtures tool_call_* |
| 010 | MUST | T-010, T-013 | fixtures |
| 011 | SHOULD | T-013, T-016 | fixtures reasoning_*, unit/core/test_run_input |
| 012 | MUST | T-010, T-019 | fixtures, unit/core/clients/test_base |
| 013 | MUST | T-014, T-015, T-030, T-034 | fixtures hitl_*, integration/test_pydantic_ai_hitl |
| 014 | MUST | T-014, T-015, T-030, T-038, T-044 | fixtures, integration/test_langgraph_hitl |
| 015 | MUST | T-015, T-030, T-044 | fixtures hitl_cancel_while_paused |
| 016 | MUST | T-009, T-013, T-016, T-030 | unit/core/test_patch, fixtures state_* |
| 017 | SHOULD | T-030 | unit/state/test_agent_state_handlers |
| 018 | MUST | T-012, T-015, T-017, T-028, T-034 | unit/core/test_tools, unit/state/test_driver_client_tools |
| 019 | MUST | T-037 | unit/components/test_tools |
| 020 | SHOULD | T-026, T-030 | unit/state/test_agent_state_handlers |
| 021 | MUST | T-019, T-020, T-022, T-023 | unit/core/clients/*, integration/test_http_client |
| 022 | MUST | T-033, T-034, T-035 | unit/adapters/test_pydantic_ai_unit, integration/test_pydantic_ai_hitl |
| 023 | MUST | T-036, T-037, T-038, T-039 | unit/components/* |
| 024 | MUST | T-017, T-031 | unit/core/test_tools, integration/test_responsiveness |
| 025 | MUST | T-029, T-031 | unit/state/test_projection, integration/test_secret_hygiene |
| 026 | SHOULD | T-026 (026.2); 026.1 by Reflex behavior, contract-tested in T-004 | unit/state/test_driver_streaming, contract/test_reflex_facts |
| 027 | SHOULD | T-026 | unit/state/test_driver_streaming |
| 028 | COULD | T-030 | unit/state/test_agent_state_handlers |
| 029 | MUST | T-040 | smoke/test_quickstart |
| 030 | MUST | T-040, T-046, T-047, T-048 | smoke/* |
| 031 | MUST | T-001, T-003, T-032 | CI core-no-extras, unit/adapters/test_require |
| 032 | MUST | T-002, T-003, T-041, T-052 | CI workflows |
| 033 | MUST | T-005, T-050, T-051 | `mkdocs build --strict`, file existence |
| 034 | MUST (034.5 SHOULD) | T-042, T-043, T-044, T-045 | unit/adapters/test_langgraph_*, integration/test_langgraph_hitl |

**Deferred SHOULD/COULD:** none. All are scheduled. They follow the Plan §6 cut order if
the schedule slips.
**Non-REQ tasks:** T-024 (spike enabling the WP3 tests) and T-046 (example plumbing for
REQ-030.2) are traced to TD OQ-1 and REQ-030.2 respectively. There are no orphans.

## Execution log

| Date | Tasks | Result | Notes |
|---|---|---|---|
| 2026-10-30 | — (specs) | ✅ | Analyze A-01…A-16 applied: Constitution v1.1, PRD v1.2, API v1.2, TD v1.1, DM v1.1, Plan v1.1, Tasks v1.1. T-017 now listed before T-016 (IDs kept). |
| — | — | — | First batch proposed: T-001, T-002, T-003, T-004, T-005 (WP0) |
