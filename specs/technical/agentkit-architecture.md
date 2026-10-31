# reflex-agentkit v0.1 — Technical Design Document

## Metadata

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo (`ecrespo`) |
| **Status** | `APPROVED` (2026-10-30) |
| **Version** | 1.9 |
| **Date** | 2026-10-30 |
| **PRD** | [`specs/prd/agentkit-v0.1.md`](../prd/agentkit-v0.1.md) (APPROVED) |
| **API Spec** | [`specs/api/agentkit-python-api-v1.md`](../api/agentkit-python-api-v1.md) (APPROVED) |
| **Governed by** | [`specs/constitution.md`](../constitution.md) v1.0 |

---

## 1. Context

The PRD fixes *what* v0.1 does and the API Spec fixes the public names and contracts. This
document fixes *how*:
- pinned dependency versions,
- module structure,
- the run engine inside a Reflex background task (streaming, batching, cancellation,
  client-tool rounds),
- the adapters' internals,
- security, observability and the test strategy.

It also closes the open items PRD D-01/D-02/D-03 and API Q-1…Q-5.

**Everything marked "verified" was checked on 2026-10-30 against the real packages**
installed in a throwaway environment (reflex 0.10.1, ag-ui-protocol 1.0.0,
pydantic-ai-slim 2.64.0, ag-ui-langgraph 0.0.47, langgraph 1.2.19). Spike scripts were not
committed. The checks are reproduced as permanent contract tests (§8.4).

## 2. Technical Objectives

| Objective | Target | Source |
|---|---|---|
| Event → state applied | < 1 ms p95 per event (reducer) | NFR-01 |
| Push rate during streaming | ≤ 1 push per `flush_interval_ms` (default 50 ms → ≤ 20/s) | REQ-006, NFR-02 |
| Cancel → `cancelled` visible | ≤ 1 s, single- and multi-worker | REQ-007.1, 007.6 |
| Other clients' events during a run | < 200 ms | REQ-024.1 |
| `core` importable with no extras and without `reflex` | enforced by CI job | Art. 1, REQ-031.2 |
| `core` coverage | ≥ 85 % | Art. 6 |
| `mypy --strict` on `core` | 0 errors | Art. 7 |

## 3. Proposed Architecture

### 3.1 High-level diagram

```
Browser (Reflex frontend, compiled; no custom JS)
   │  Socket.IO (Reflex built-in): events ↑  state deltas ↓
   ▼
Reflex backend worker (one asyncio loop)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ reflex_agentkit.state                                                    │
 │  AgentState (mixin)                                                      │
 │   ├─ foreground handlers: send_message, approve_tool, cancel_run, …      │
 │   │    (validate → pure command fn → set _pending_start → return bg evt) │
 │   └─ background handler drive_run  ──► RunDriver (pure asyncio)          │
 │                                         │ owns ConversationState locally │
 │          ┌──── flush every N ms ◄───────┤ reduce() each event            │
 │          │  async with self:            │ runs client tools between      │
 │          │   ownership + cancel check   │ rounds                         │
 │          │   project → public vars      │                                │
 │          ▼                              ▼                                │
 │    Reflex state manager           RunRegistry (per process)              │
 │   (memory | disk | redis)         {(token, run_id) → task, client}       │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ reflex_agentkit.core (no reflex import)                                  │
 │  reduce() · commands · RunInputBuilder · ClientTool · errors · patch     │
 │  AgentClient ◄── HttpAGUIClient (httpx + SSE parser)                     │
 │              ◄── InProcessAGUIClient ◄── AGUIAgent                       │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ reflex_agentkit.adapters (extras)                                        │
 │  PydanticAIAgent ── AGUIAdapter.run_stream()      (pydantic-ai-slim)     │
 │  LangGraphAGUIAgent ── ag_ui_langgraph.LangGraphAgent subclass           │
 └──────────────────────────────────────────────────────────────────────────┘
          │ HTTP SSE (sidecar mode only)
          ▼
   Any AG-UI server (PydanticAI, LangGraph, Agno, CrewAI, …)
```

### 3.2 Components

| Component | Module | Responsibility | Depends on |
|---|---|---|---|
| Value types | `core/models.py` | `ChatMessage`, `ToolCall`, `PendingInterrupt`, `CustomEventRecord`, enums | stdlib, pydantic |
| `ConversationState` | `core/conversation.py` | Immutable aggregate owned by the reducer (fields → Data Model) | models |
| Reducer | `core/reducer.py` | `reduce(state, event)`: one private function per event family, plus a dispatch table | models, `ag_ui.core`, patch |
| Commands | `core/commands.py` | `begin_run`, `apply_approval`, `apply_rejection`, `apply_interrupt_response`, `apply_cancel`, `apply_client_tool_result`, `resume_entries` | models |
| Run input | `core/run_input.py` | `RunInputBuilder`: ConversationState → `RunAgentInput` (message conversion, encrypted reasoning, tools, resume) | `ag_ui.core` |
| JSON Patch | `core/_patch.py` | Typed façade over `jsonpatch`: atomic apply, error → `PatchError` | `jsonpatch` |
| Client tools | `core/tools.py` | `client_tool` decorator, schema from type hints, `ClientTool.invoke()` (sync → thread, timeout) | pydantic |
| Clients | `core/clients/{base,http,in_process,sse}.py` | `AgentClient`/`AGUIAgent` protocols, HTTP SSE client, in-process client, SSE line parser | httpx, `ag_ui.core` |
| Errors | `core/errors.py` | Exception hierarchy (API §9.1), `ErrorCode` | — |
| `RunDriver` | `state/_driver.py` | The run engine (§3.3). Pure asyncio. Talks to state only through the `StateAccess` port. | core |
| `RunRegistry` | `state/_registry.py` | Per-process map of live runs for fast cancel | — |
| `AgentState` | `state/agent_state.py` | Reflex mixin: config validation in `__init_subclass__`, public vars, handlers, `StateAccess` implementation, projection | reflex, core |
| Components | `components/*.py` | Built-in Reflex components only | reflex, state |
| Adapters | `adapters/{pydantic_ai,langgraph}.py`, `adapters/_require.py` | Framework → `AGUIAgent`; friendly `AdapterNotInstalledError` | extras |

### 3.3 Data flow

#### Flow A — send a message, stream the reply (happy path)

1. The browser calls `send_message(text)`. This is a foreground handler and runs under
   the state lock.
2. It validates the text (REQ-001.4–6), calls `commands.begin_run(conv, text)` (pure:
   appends the user message, assigns `thread_id` if empty and a new `run_id`, sets status
   `running`), and writes the new `_conv`. It stores `_pending_start = run_id`, projects
   the public vars, and returns `AgentState.drive_run` (a background event; Reflex 0.10.1 rejects
   private event handlers, so the name is public and the claim token below guards it).
3. `drive_run` starts. Under `async with self`, it **claims** the start: it checks
   `_pending_start == _conv.run_id`, clears `_pending_start`, and copies `_conv` locally.
   IF there is nothing to claim, it returns. This defeats forged or duplicate triggers
   (§6.1).
4. Outside the lock, the driver calls `create_client()`, builds the input with
   `RunInputBuilder` and `prepare_run_input`, and registers `(token, run_id)` in
   `RunRegistry`.
5. It starts a **pump task** that iterates `client.stream(input)` and puts events into a
   bounded `asyncio.Queue(maxsize=1024)`. The consumer loop waits on `queue.get()` with a
   timeout equal to the time left until the next flush deadline (DD-003).
6. For each event: `conv = reduce(conv, event)`. Diagnostics are logged and cleared.
7. When the flush deadline passes, or a terminal event arrives, the driver enters
   `async with self`:
   - **ownership check:** `self._conv.run_id == my_run_id and self._cancel_requested != my_run_id`;
   - write `_conv = conv`;
   - project `conv` onto the public vars;
   - exit, and Reflex emits the delta.
   The `on_custom_event` hooks for CUSTOM events received since the last flush run here.
8. On `RUN_FINISHED`, the driver flushes, unregisters, and closes the client stream. It
   then decides:
   - no interrupts and no unfinished client-tool calls → done, status `idle`;
   - interrupts → status `awaiting_input`; the task ends (Flow C picks up);
   - client-tool calls → Flow B.
9. `on_run_end(status)` is called once, after the final flush.

#### Flow B — client-side tool round (REQ-018)

1. After `RUN_FINISHED`, the driver finds the tool calls that are `is_client_tool` and
   `running` (handed off at `TOOL_CALL_END`).
2. Approval-required tools are moved to `pending_approval` locally. The driver flushes and
   ends the task (Flow C resumes it). Other tools continue below.
3. Each handler runs **outside the lock** through `ClientTool.invoke(args, timeout)`. Sync
   handlers run in `asyncio.to_thread`. Several calls run concurrently with
   `asyncio.gather`.
4. `commands.apply_client_tool_result` records the result (or the error text, REQ-018.4)
   and appends a `tool` message. The driver flushes.
5. The driver starts the follow-up run in the same task: a new `run_id`, back to A.4. The
   status stays `running` throughout.
6. IF the number of consecutive client-tool rounds exceeds `max_client_tool_rounds`
   (default 8, DD-009), THEN the driver stops with `error_code=CLIENT_TOOL_LOOP_LIMIT`.

#### Flow C — approvals and interrupts (REQ-013–015)

1. A paused run ends with `awaiting_input`. `_conv` holds the open interrupts and the
   answers so far (empty).
2. `approve_tool`, `reject_tool` and `respond_to_interrupt` are foreground handlers. They
   validate, apply the pure command, and project.
3. WHEN `commands.all_answered(conv)` holds, the handler calls `begin_run(conv, resume=…)`,
   sets `_pending_start`, and returns `drive_run`. The flow continues at A.3 with
   `RunAgentInput.resume` built by `commands.resume_entries(conv)`, which reads the
   entries `begin_run` captured in `conv.resume` (DM §3.10 v1.6) before it cleared the
   interrupts and answers.
4. For client tools that were approved, the driver first runs the handler with the
   (possibly edited) args, Flow B.3, and then continues with the follow-up run. Client-tool
   approvals are local and never round-trip to the agent.

#### Flow D — cancellation (REQ-007, 015)

1. `cancel_run` runs in the foreground under the lock.
   - **If status is `running`:** it sets `_cancel_requested = run_id`, then looks up
     `RunRegistry[(token, run_id)]`. If the run lives in this worker, it calls
     `pump_task.cancel()` and `driver_task.cancel()` right away.
   - **If status is `awaiting_input`:** it applies `commands.apply_cancel` (open approvals
     become `rejected`, and the interrupt IDs are remembered for REQ-015.3). It sets
     status `cancelled` and returns. No task is involved.
2. In the driver (same worker), `CancelledError` reaches the consumer. In `finally`, the
   pump task is cancelled. `client.stream` is closed with `aclose()`, so httpx closes the
   connection (REQ-007.2), or the in-process agent's task is cancelled (REQ-007.3). The
   driver then does a final `async with self` that applies `commands.apply_cancel`
   (partial message kept; streaming/running tools → `error` "cancelled", REQ-007.4) and
   sets status `cancelled`. The `CancelledError` is not re-raised: the driver owns the task
   and nothing awaits it.
3. **Multi-worker (redis):** the registry lookup misses. The owning driver sees
   `_cancel_requested == my_run_id` at its next flush. The consumer timeout guarantees
   that a flush tick happens at least every `max(flush_interval_ms, 100 ms)` even when the
   upstream is silent. The driver then performs step 2 itself. Latency is at most one tick
   plus lock wait, well under the 1 s target. REQ-007.6 is therefore met by design; it
   stays SHOULD only until the multi-worker test (T-redis, §8.2) is green.
4. Events that were already queued are discarded (REQ-007.5): the driver stops consuming
   once the ownership check fails.

#### Flow E — failures

| Failure | Detected by | Result |
|---|---|---|
| Non-2xx response | `HttpAGUIClient` → `AgentHTTPError` | `error`, `AGENT_HTTP_ERROR`; partial content kept |
| Read timeout, EOF, wrong content type, connect error | `HttpAGUIClient` → `AgentStreamError` | `error`, `AGENT_STREAM_ERROR` |
| In-process agent raises, or `create_client()` fails | `AgentStreamError(reason="agent_raised")` from the pump task / exception in A.4 | `error`, `AGENT_EXCEPTION`; exception type logged at ERROR, traceback at DEBUG (§5.3) |
| `RUN_ERROR` | reducer | `error`, `AGENT_RUN_ERROR` |
| EOF in-process without a terminal event | driver (iterator exhausted) | `error`, `AGENT_STREAM_ERROR` (REQ-004.4) |
| Invalid event JSON or schema | client skips it + warning | run continues (REQ-012.3) |
| Ownership lost: `new_thread`, state expired or reset (REQ-026.2) | flush ownership check | silent stop; upstream closed; no state write |
| Client disconnects (REQ-026.1) | — (Reflex does **not** cancel background tasks on disconnect: verified in `BaseStateEventProcessor._on_disconnect`, which cancels only hydration) | run continues; state is complete on reconnect with the same token |
| Worker shutdown | Reflex cancels outstanding tasks (`EventProcessor._stop_tasks`) | driver `finally`: best-effort final flush with status `error`, `AGENT_STREAM_ERROR` "server shutting down" |

## 4. Design Decisions

### DD-001 — Pinned dependency ranges (verified on PyPI, 2026-10-30)

| Package | Range | Latest verified | Notes |
|---|---|---|---|
| Python | `>=3.11,<3.14` (CI: 3.11, 3.12, 3.13) | — | reflex and pydantic-ai require ≥ 3.11 |
| `reflex` | `>=0.10.1,<0.11` | 0.10.1 (2026-10-27) | Pre-1.0: minor bumps may break, so the cap is one minor |
| `ag-ui-protocol` | `>=1.0.0,<2` | 1.0.0 (2026-09-17) | Spec 1.0: 31 events, `RunFinishedOutcome` ∈ {success, interrupt, cancelled}, `ResumeEntry`. `THINKING_*` already removed from the Python enum. |
| `httpx` | `>=0.28,<1` | 0.28.1 | Already a transitive dependency of Reflex |
| `pydantic` | `>=2.11.2,<3` | 2.14.2 | The floor comes from ag-ui-protocol |
| `jsonpatch` | `>=1.33,<2` | 1.38 (2026-10-26) | DD-007 |
| **extra `pydantic-ai`** | `pydantic-ai-slim[ag-ui,anthropic,openai]>=2.64,<3` | 2.64.0 | `anthropic`: Claude is the default model. `openai`: the OpenAI-compatible provider used for **Ollama**. The floor is the version the interrupt contract was verified on. |
| **extra `langgraph`** | `ag-ui-langgraph[fastapi]>=0.0.47,<0.1`, `langgraph>=1.2,<2` | 0.0.47 / 1.2.19 | `[fastapi]` is required: ag-ui-langgraph's `__init__` imports `fastapi` unconditionally although it declares it optional (an upstream bug, verified; we will report it). |
| **extra `all`** | both of the above | — | |

**Dev group** (uv `[dependency-groups]`): `pytest`, `pytest-asyncio`, `pytest-cov`,
`hypothesis`, `mypy`, `ruff`, `uvicorn` (fake SSE server, DD-010), `redis` (T-redis), `mkdocs-material`.

A weekly CI job runs the suite against the newest versions of every dependency, with no
caps (`uv lock --upgrade --prerelease=no` in a temporary lock) to detect drift early. It is
allowed to fail and opens an issue when it does.

### DD-002 — Where the agent runs (closes PRD D-01)

- **Context:** Reflex runs every client of a worker on one asyncio loop. Background events
  release the state lock and re-acquire it on each `async with self` (verified in
  `base_state_processor.py`).
- **Options:**
  - A: in-process asyncio task (the background event itself);
  - B: a mandatory sidecar process with IPC;
  - C: a thread per run.
- **Criteria:** the 30-line quickstart, cancellation semantics, blocking risk, deployment
  simplicity.
- **Decision:** A by default. "Sidecar" means running the agent behind its own AG-UI
  HTTP server and pointing `HttpAGUIClient` at it, so there is no new IPC (PRD D-01). C is
  rejected: cancelling a thread is cooperative, and it would bypass the protocol's async
  model.
- **Consequences:** the adapter contract forbids blocking (API §7.1.3). Sync client-tool
  handlers are offloaded. A test with a slow fake agent guards REQ-024.1. The docs
  recommend the sidecar for CPU-bound agents.

### DD-003 — Pump task + queue instead of `wait_for(anext(...))`

- **Context:** batching needs "wait for the next event, but no longer than the flush
  deadline". `asyncio.wait_for(it.__anext__(), t)` cancels the generator's `__anext__` on
  timeout, and that **corrupts async generators** (the generator is closed mid-await).
- **Options:**
  - A: `wait_for` on `anext`;
  - B: a pump task that forwards into an `asyncio.Queue`; the consumer uses
    `wait_for(queue.get(), t)`;
  - C: no timeout (flush only when events arrive).
- **Decision:** B. A breaks the stream. C cannot observe a cross-worker cancel during a
  silent upstream (a model thinking for 30 s).
- **Consequences:** one extra task per run. The bounded queue (1024) gives backpressure:
  a slow consumer slows the reads from upstream instead of growing memory. Cancelling the
  pump task is what closes upstream.

### DD-004 — Single writer during a run

- **Decision:** while `run_status == running`, only the `RunDriver` writes `_conv` and the
  public vars. Foreground handlers may write only `_cancel_requested`, and `new_thread`
  may replace `_conv` (which the driver then detects as ownership loss). Every other
  handler is a no-op while running (API §4.3 preconditions).
- **Why:** it removes lost-update races between the driver's local `conv` and foreground
  writes, without fine-grained locking. It is also what makes the pure reducer usable: one
  owner, deterministic order.

### DD-005 — Batching as "flush on deadline", not "debounce"

- A flush happens at the first event after the deadline, at the deadline when the queue is
  idle, and immediately on terminal events (REQ-006.2).
- A debounce (waiting for quiet) is rejected because it could postpone updates
  indefinitely during a steady token stream.
- `flush_interval_ms = 0` means flush after every event (REQ-006.4).
- The push count per second is bounded by `1000 / flush_interval_ms`. REQ-006.3 is
  checked against a counting `StateAccess` fake.

### DD-006 — Configuration via explicit `ClassVar` (closes API Q-1)

- **Verified:** an unannotated `agent = obj` in a subclass of a Reflex mixin is turned into
  a state var (`VarTypeError: State vars must be of a serializable type`), even when the
  mixin declares `agent: ClassVar[...]`. An explicit `agent: ClassVar = obj` in the
  subclass works, and `agent` is not in `base_vars`.
- **Options:**
  - A: explicit `ClassVar` in user code;
  - B: intercept the namespace in the mixin's `__init_subclass__` before Reflex sees it;
  - C: a decorator `@agent_state(agent)`.
- **Decision:** A, the pre-approved fallback. B depends on Reflex internals that change
  between minors. C is unidiomatic for Reflex and hides the class var from type checkers.
- **Mitigation:** `AgentState.__init_subclass__` validates the subclass *before* calling
  Reflex's `__init_subclass__` (verified on Reflex 0.10.1: the metaclass records `mixin=`
  in the class's own `_mixin` and the fields are bound later, in `__init_subclass__`).
  A configuration attribute defined without `ClassVar` therefore raises our
  `ConfigurationError` naming the attribute, instead of Reflex's `VarTypeError`, and an
  invalid class is never registered in the state tree. The README and the docstring
  still show the `ClassVar` form.

### DD-007 — JSON Patch: `jsonpatch` library behind a typed façade

- **Options:**
  - A: `jsonpatch` (maintained; 1.38 released 2026-10-26; pure Python; RFC 6902 complete
    including `test`);
  - B: a vendored implementation (~200 lines plus the RFC test suite).
- **Decision:** A. RFC conformance is solved upstream.
- **Consequences:** `jsonpatch` ships no types, so `core/_patch.py` is the only importer,
  with one `# type: ignore[import-untyped]  # jsonpatch ships no stubs`, as Art. 7 allows.
  The façade guarantees atomicity: it applies to a deep copy and either commits it or
  raises `PatchError`.

### DD-008 — State layout: one backend-only aggregate plus projected public vars

- **Decision:** `_conv: ConversationState` lives in a backend-only var (pickled by the
  Redis manager and never sent to the browser). The public vars (API §4.2) are a
  **projection** written at every flush.
- **Why:**
  - the reducer operates on one immutable value;
  - the browser never sees backend-only data (encrypted reasoning values, remembered
    cancelled interrupt IDs, raw resume answers);
  - persistence in v0.2 serializes one object (EP-2).
- **Cost:** the projection is duplicated in memory. Messages are typically small, and
  Reflex sends only changed vars.
- **Representation of public vars** (dataclasses vs. TypedDicts in `list[...]` vars):
  fixed in the Data Model.

### DD-009 — Client-tool rounds run inside one background task, with a loop limit

- Client-tool execution and the follow-up run stay in the same driver task (Flow B), so
  the status stays `running` and there is no gap in which the user could send a
  conversation-breaking message.
- A new `ClassVar` `max_client_tool_rounds: int = 8` and a new error code
  `CLIENT_TOOL_LOOP_LIMIT` guard against a model looping on a UI tool. **This is an
  additive API change** (API §4.1 and §9.2; see §10, A-2).

### DD-010 — Test transport for `HttpAGUIClient`: a real local server

- **Options:**
  - A: `httpx.MockTransport` or `respx`;
  - B: a real Starlette app served by `uvicorn` on an ephemeral port inside the test
    process.
- **Decision:** B. REQ-007.2 requires observing that the *server* sees the disconnect,
  which a mock transport cannot show. SSE framing edge cases (multi-line `data:`,
  comments, CRLF) are also covered by unit tests on the pure SSE parser.

### DD-011 — PydanticAI adapter internals (closes API Q-3)

- `PydanticAIAgent.run(input)` does `AGUIAdapter(agent=a, run_input=input).run_stream(...)`
  and yields the events. **Verified:** with `TestModel(call_tools=["book_hotel"])` and a
  `requires_approval=True` tool, the stream ends with
  `RUN_FINISHED(outcome=interrupt, interrupts=[Interrupt(id="int-<call_id>", reason="tool_call", tool_call_id=…, response_schema={approved, editedArgs, reason})])`.
- **Q-3 resolved positively:** `run_stream(output_type=[agent.output_type, DeferredToolRequests])`
  works **without** the user declaring `DeferredToolRequests`. The adapter injects it when
  the agent's output type does not already include it. REQ-022.4's configuration error is
  therefore never raised for this case, and the quickstart loses two lines (§10, A-1).
- `deps` / `deps_factory` are passed as `run_stream(deps=...)`. `**run_kwargs` is passed
  through.
- Message history: `AGUIAdapter` defaults to `manage_message_history="client"`, which
  matches our design, since `RunInputBuilder` sends the full history.
- PydanticAI prints an observability banner on first use. The docs mention
  `PYDANTIC_AI_NO_BANNER=1`; the library does not modify the environment.

### DD-012 — LangGraph adapter internals (closes API Q-4 and PRD D-03 mechanics)

- `LangGraphAGUIAgent` **subclasses** `ag_ui_langgraph.LangGraphAgent` with
  `emit_interrupt_outcome=True`, `enable_legacy_on_interrupt_event=False` and
  `emit_raw_events=False` (RAW events would flood the queue with provider chunks we do not
  render).
- **Verified (Q-4):** `ag_ui_langgraph.interrupts.lg_interrupt_to_agui` builds the AG-UI
  `Interrupt` from the interrupt value. A dict value's `reason`, `message`, `toolCallId`
  and `responseSchema` keys map directly to `Interrupt` fields. So
  `request_tool_approval()` only has to call
  `interrupt({"reason": "tool_call", "toolCallId": id, "message": msg, "toolName": name, "args": args, "responseSchema": APPROVAL_SCHEMA})`.
  No event rewriting is needed, and the marker-key fallback is unnecessary.
- **Verified issue:** for more than one resume entry, the upstream
  `_build_command_from_agui_resume` wraps the answers in an `__agui_resume_map__` sentinel
  dict. Every interrupted node would then receive the whole map instead of its own answer.
  We override that method to produce LangGraph's native multi-resume
  `Command(resume={interrupt_id: payload, ...})`.
  - It is a private upstream method, so the override is protected by a contract test
    (§8.4) and by the `<0.1` cap.
  - A single resolved entry stays `Command(resume=payload)`.
  - A cancelled entry for a `tool_call` interrupt becomes
    `{"approved": False, "reason": "cancelled"}`, so `request_tool_approval` returns
    `ApprovalDecision(approved=False, reason="cancelled")`.
  - For generic interrupts, cancellation keeps the upstream `{"__agui_cancelled__": True}`
    sentinel. The docs tell graph authors to check it.
- The checkpointer check (REQ-034.4) happens in `__init__` (`graph.checkpointer is None`
  → `ConfigurationError`).
- **Verified (T-042):** `LangGraphAgent` keeps per-run state on the instance
  (`active_run`, `messages_in_process`), and its FastAPI endpoint clones it per request.
  Our instance is a `ClassVar` shared by every session, so `run()` runs a fresh `clone()`
  each time; `clone()` is overridden because our `__init__` signature differs.
- **Verified (T-042):** upstream `get_state_snapshot` keeps every output key plus
  `tools`, so a `MessagesState` graph puts its whole LangChain message history into each
  `STATE_SNAPSHOT`. That would duplicate the conversation in `shared_state` and reach the
  64 KiB cap on long threads. The override drops the `messages` and `tools` keys: the
  conversation arrives through the message events and `MESSAGES_SNAPSHOT`, and the tools
  through `RunAgentInput.tools`.
- `legacy_interrupts=True` (REQ-034.5, SHOULD) flips the two interrupt flags back and
  maps `CUSTOM(name="on_interrupt")` to a synthetic `pending_interrupt` resumed through
  `forwarded_props.command.resume`. It is off by default, documented as a compatibility
  mode, and is the **only** place where `forwarded_props` is used.

### DD-013 — Tool renderers via `rx.match` (closes API Q-5)

- **Verified:** `rx.foreach(State.tool_calls, lambda tc: rx.match(tc.name, ("show_chart", …), ("book_hotel", …), default))`
  renders with dataclass-typed list vars.
- `tool_call_card` builds the `rx.match` at compile time from the `tool_renderers` mapping.
  An empty mapping renders the default body with no `rx.match`.
- A full `reflex` compile of the Dojo examples (§8.3) is the end-to-end check.

### DD-014 — Thread and token identity (closes PRD D-02)

- **Verified:** Reflex keeps the client token in `window.sessionStorage["token"]`
  (`reflex_base/.templates/web/utils/state.js`): one token per tab, preserved across
  reloads, new in a new tab.
- **Verified:** with Redis, state expires after `redis_token_expiration` (default 3600 s).
- So a thread survives a reload (same token → same `_conv`) and is lost when the state
  expires. A running driver detects the expiry through the ownership check and stops
  (REQ-026.2). `thread_id` is independent of the token, as decided. v0.2 persistence
  attaches threads to users.

### DD-015 — Message rendering safety

- Assistant content is rendered with Reflex's built-in `rx.markdown`, with **no raw HTML**
  (no `rehype-raw` plugin). Tool args and results are rendered as text or code blocks,
  never as markdown.
- **Verified (T-036, OQ-3):** `rx.markdown` in Reflex 0.10.1 **enables raw HTML by
  default** (`use_raw=True` adds the `rehype-raw` plugin). Every markdown the library
  renders passes `use_raw=False`, and a test asserts that the rendered component carries
  no `rehypeRaw` plugin, so `<img src=x onerror=…>` in model output stays text.

## 5. Patterns and Conventions

### 5.1 Code structure

```
src/reflex_agentkit/
├── __init__.py              # __version__ literal; eager re-exports of core names; LAZY (PEP 562 __getattr__) re-exports of AgentState/components (API §1)
├── py.typed
├── core/                    # MUST NOT import reflex or any extra (import-check test)
│   ├── __init__.py
│   ├── models.py  conversation.py  reducer.py  commands.py  run_input.py
│   ├── tools.py   errors.py  _patch.py  _log.py
│   └── clients/  base.py  http.py  in_process.py  sse.py
├── state/
│   ├── __init__.py  agent_state.py  _driver.py  _registry.py  _projection.py
├── components/
│   ├── __init__.py  chat.py  messages.py  composer.py  tools.py  approval.py  status.py  shared_state.py
└── adapters/
    ├── __init__.py  _require.py  pydantic_ai.py  langgraph.py
tests/
├── fixtures/events/*.jsonl  # one file per scenario; header line = expected final state digest
├── unit/core/  unit/state/  unit/components/  unit/adapters/
├── integration/             # fake SSE server, in-process agents, test models
├── contract/                # upstream behavior we rely on (§8.4)
└── smoke/                   # compile each example
examples/  quickstart/  pydantic_ai_dojo/  langgraph_dojo/
docs/      (MkDocs Material)   docs/integrations/ (upstream PR drafts)
```

### 5.2 Applied patterns

- **Functional core / imperative shell:** `core` holds pure functions over immutable
  values. `state` is the shell that does I/O, locking and Reflex.
- **Ports and adapters:**
  - `AgentClient` and `AGUIAgent` are ports. HTTP, in-process, PydanticAI and LangGraph
    are adapters.
  - `StateAccess` is the driver's port to Reflex:
    `async with access.locked() as view: view.conv, view.cancel_requested, view.publish(conv)`.
  - The driver is therefore tested with an in-memory fake, without Reflex.
- **Dispatch table** in the reducer: `dict[EventType, Callable]`. Unknown types fall
  through to the diagnostic path (REQ-012.2), so a new upstream type never needs a code
  change to stay safe.
- **Claim token** (`_pending_start`) for background starts (§6.1).

### 5.3 Error handling

- Exceptions follow API §9.1.
- Rule: **nothing escapes `drive_run`**. Every exception maps to a status and an error
  code in the final flush. The failure is logged at ERROR with the `thread_id`/`run_id`
  context, naming only the error code and the exception type; the traceback is logged at
  DEBUG, because an agent's exception message may quote user content (REQ-027.2). `CancelledError` is handled as cancellation and not
  re-raised (the driver owns the task).
- `ConfigurationError` is raised at import or startup time (`__init_subclass__`, adapter
  `__init__`, `client_tool` decoration), never mid-session.
- Client-tool handler errors become tool results, not run errors (REQ-018.4).

## 6. Security

### 6.1 Attack surface

| Vector | Risk | Control |
|---|---|---|
| Browser triggers any public event handler with arbitrary args (Reflex event handlers are callable from the client) | State corruption, forged runs | Each handler validates its preconditions (API §4.3). `drive_run` takes **no arguments** and runs only if it can claim `_pending_start` (one-shot), so a forged trigger is a no-op. |
| Oversized payloads in `send_message`, `approve_tool(edited_args)`, `respond_to_interrupt` | Memory / cost abuse | `max_message_length` (32k chars). `edited_args` and interrupt payloads are capped at 64 KiB of serialized JSON → `INVALID_EDITED_ARGS` / ignored with a warning. Reflex's own frame size limit is the outer bound. |
| `approve_tool` on another user's call | Cross-user action | Impossible: state is per token (REQ-003). Call IDs are looked up only in that session's `_conv`. |
| LLM output with HTML/JS (XSS) | Script execution in users' browsers | DD-015: no raw HTML in markdown; args and results rendered as text. |
| Prompt injection leading to dangerous tool calls | Unwanted actions | Product control: `requires_approval` tools (REQ-013/018.3) and the edit/reject UI. Documented in the security model page (REQ-033.3). |
| A malicious or compromised AG-UI server (sidecar or third party) | Malformed events, huge streams | Schema validation per event (REQ-012.3). Bounded queue. `max_message_length` is *not* applied to agent output. Read timeout (REQ-021.4). Documented: the agent endpoint is trusted infrastructure. |
| SSRF via `HttpAGUIClient` URL | — | The URL is developer configuration (`ClassVar` / `create_client`), never taken from the browser. |

### 6.2 Sensitive data

| Data | Where it lives | Reaches the browser? |
|---|---|---|
| API keys (model providers) | Environment, read by the agent framework | No |
| `HttpAGUIClient` headers | Client instance (ClassVar or `create_client` result), `RunRegistry` | No. Never logged, never in errors (REQ-021.6). |
| Agent and client objects | ClassVars, registry | No (verified pattern, DD-006) |
| Encrypted reasoning values | `_conv` (backend-only) | No (REQ-011.2) |
| Messages, tool args and results | Public vars | **Yes, by design.** The docs state it. Logging above DEBUG excludes them (REQ-027.2). |

Test REQ-025.2: run the quickstart with `TestModel` and `HttpAGUIClient(headers={"Authorization": "Bearer SECRET-123"})`
against the fake server. Serialize the client-visible state the way Reflex's delta
encoder would. Assert that `SECRET-123` and the configured API key value do not appear.

## 7. Observability

### 7.1 Logging

- Logger `reflex_agentkit`, with child loggers per module (`reflex_agentkit.core.reducer`,
  `reflex_agentkit.state.driver`, …).
- A `LoggerAdapter` adds `thread_id` and `run_id` to every run-scoped record (REQ-027.1).

| Level | Contents |
|---|---|
| DEBUG | each event type (no payload), skipped unknown events, SSE body excerpts on HTTP errors |
| INFO | run start/finish (status, duration, event count, flush count) |
| WARNING | reducer diagnostics (out-of-order, invalid patch), hook exceptions |
| ERROR | driver failures with traceback |

Message contents and tool args or results are logged only at DEBUG (REQ-027.2).

### 7.2 Metrics

None exported (no telemetry, Constitution Art. 3). The INFO run summary (duration,
`events`, `flushes`, `client_tool_rounds`) is the hook for host apps that ship logs to
their own systems.

### 7.3 Alerts

Not applicable (library).

## 8. Testing Strategy

| Layer | Tooling | What | REQs |
|---|---|---|---|
| Reducer, unit | pytest, JSON Lines fixtures | One fixture or more per event type. Out-of-order, duplicate, unknown, invalid-patch, chunk and `MESSAGES_SNAPSHOT` scenarios. The expected final state is in the fixture header. **Test-first** (Art. 6). | 005, 008–012, 016 |
| Reducer, property | hypothesis | Random event sequences: never raises (totality), deterministic, `streaming` false after a terminal event | 005.1–2 |
| Commands, unit | pytest | Approve, edit, reject, interrupt queue, cancel-while-paused, resume-entry construction | 013–015 |
| `RunInputBuilder` | pytest | Message conversion round-trip, encrypted reasoning, tools, resume | 001.2, 011.2, 016.7 |
| SSE parser | pytest | Multi-line data, comments, CRLF, partial chunks | 021.2 |
| `HttpAGUIClient` | pytest + local uvicorn Starlette fake server (DD-010) | Happy path, non-2xx, wrong content type, read timeout, EOF, **server observes disconnect on cancel**, headers never in errors or logs | 021, 007.2, 004.4 |
| `RunDriver` | pytest-asyncio + `StateAccess` fake + scripted fake clients | Batching counts, flush on terminal, cancel (registry path and flag path), ownership loss, client-tool rounds, loop limit, handler timeout and exception | 006, 007, 018, 026 |
| `AgentState` | Reflex state tested in process through Reflex's `BaseStateEventProcessor` over `StateManagerMemory` (OQ-1, `tests/helpers/reflex_harness.py`) | Preconditions, projection, `ClassVar` validation, secret-leak test | 001–004, 013–017, 025 |
| Responsiveness | pytest-asyncio | A slow fake agent (offloaded 2 s of work) plus a second client's handler latency < 200 ms | 024.1 |
| Multi-worker cancel (T-redis) | pytest + Redis service container in CI (one job) | Cancel handled by a "different worker": two `StateManagerRedis` instances | 007.6 |
| Adapters | `TestModel` (PydanticAI); `FakeListChatModel` / scripted graph with `MemorySaver` (LangGraph) | Approval round-trip including edited args (the tool runs with the edited args), generic interrupt, multi-interrupt resume, cancelled interrupt, checkpointer error | 022, 034 |
| Components | Reflex component render to string (no browser) | Structure, aria-labels, disabled states, renderer dispatch, markdown escaping | 019, 023 |
| Smoke | `reflex` compile of each example, with `TestModel` / fake LLM injected through env | Every example compiles. Quickstart ≤ 30 lines. The README block equals the file. | 029, 030 |
| Benchmarks | pytest marker `bench` (not in the default run; weekly CI) | Reducer per-event p95; 20-client flush lag | NFR-01, 04 |

### 8.4 Contract tests (upstream behavior we depend on)

These pin the facts verified in this document, so an upgrade that breaks them fails loudly:
1. `ag_ui.core.EventType` has the 31 v1.0 values. `RunFinishedOutcome` has the variants
   success, interrupt and cancelled. `ResumeEntry` has the fields we use.
2. PydanticAI: a `requires_approval` tool plus injected `DeferredToolRequests` produces the
   interrupt shape in DD-011, and `editedArgs` overrides the args on resume. A call to a
   frontend (client) tool ends with `RUN_FINISHED(outcome=success)`, not an interrupt
   (verified in the Analyze spike, A-18); `RunFinishedSuccessOutcome.pending_tool_call_ids`,
   when present, lists the calls awaiting client results.
3. ag-ui-langgraph: a dict interrupt value maps `reason` / `toolCallId` to the `Interrupt`
   fields. Our `_build_command_from_agui_resume` override is called and yields the native
   multi-resume.
4. Reflex: an unannotated subclass attribute becomes a var, and a `ClassVar` does not
   (this documents DD-006). Reflex does not cancel background tasks on disconnect: in
   0.10.1, `BaseStateEventProcessor._on_disconnect` cancels only hydration and unfinished
   `on_load` chains, so a run started from a user event (`send_message`) keeps going. A
   run started *from* an `on_load` handler would be cancelled with that chain; the docs
   tell users not to start runs there.

### 8.5 CI jobs (GitHub Actions)

`lint` (ruff check plus format check) · `typecheck` (mypy strict on core and state) · `test` matrix
3.11/3.12/3.13 with coverage gate (core ≥ 85 % and state ≥ 85 %) · `core-no-extras` (install without extras;
import plus core tests; assert `reflex_agentkit.core` imports no `reflex`) · `redis` (T-redis) ·
`examples-smoke` · `deps-latest` (weekly, allowed to fail) · `release` on `v*` tags (build
and trusted publishing).

## 9. Rollout

### 9.1 Deployment strategy

The library ships to PyPI as `0.1.0` on a `v0.1.0` tag. Before that, release candidates go
to TestPyPI (`0.1.0rc1`, …) with the same workflow, and a fresh-environment walkthrough of
the quickstart is done (PRD §4.2 indicator). Upstream PR drafts (REQ-033.2) are submitted
after `0.1.0` is on PyPI.

### 9.2 Backward compatibility

None to maintain (first release). This document establishes the dependency caps that
future minors will relax deliberately.

## 10. Amendments to approved specs (applied 2026-10-30: API v1.1, PRD v1.1)

The API Spec is approved but unreleased, so these are edits to v1, recorded in its change
history as v1.1, not delta specs (Art. 9 delta specs apply to shipped behavior).

| ID | Spec | Change | Why |
|---|---|---|---|
| A-1 | API §2 | Quickstart: `agent: ClassVar = PydanticAIAgent(travel_agent)`, `from typing import ClassVar`. Remove `DeferredToolRequests` (import and `output_type`). Result: **23 lines**. | DD-006 (Q-1 fallback), DD-011 (Q-3 positive) |
| A-2 | API §4.1 / §9.2 | Add `max_client_tool_rounds: ClassVar[int] = 8` and `ErrorCode.CLIENT_TOOL_LOOP_LIMIT` | DD-009 |
| A-3 | API §4.1 | Configuration table: subclasses must annotate overrides as `ClassVar` | DD-006 |
| A-4 | API §7.5 | `ConfigurationError` for a missing `DeferredToolRequests` → replaced by automatic injection | DD-011 |
| A-5 | API §7.6 | Q-4 resolved: `request_tool_approval` uses the native interrupt-value keys. Cancelled tool approval returns `ApprovalDecision(approved=False, reason="cancelled")`. Generic cancelled interrupts deliver the `{"__agui_cancelled__": True}` sentinel. | DD-012 |
| A-6 | API §8.3 | `RUN_FINISHED` with `outcome.type == "cancelled"` (exists in ag-ui-protocol 1.0) → `run_status = cancelled` | Verified type |
| A-7 | API §14 | Mark Q-1…Q-5 resolved, pointing to DD-006/011/012/013; Q-2 (`ToolContext`) stays out of v0.1 | — |
| A-8 | PRD REQ-031.1 | The extras' contents per DD-001 (`[pydantic-ai]` includes the `anthropic` and `openai` providers for Claude and Ollama) | DD-001 |

## 11. Open Questions

| ID | Question | Owner / when |
|---|---|---|
| OQ-1 | ~~The exact Reflex helper for invoking handlers on a state in tests (no browser)~~ **Resolved (T-024, 2026-10-31):** Reflex 0.10.1's own `BaseStateEventProcessor`, configured with a `StateManagerMemory` (or `StateManagerRedis`) and a duck-typed `event_namespace` that records deltas, runs foreground and background handlers for any token with no app, server or browser. `EventFuture.wait_all()` waits for a handler's whole chain; background-task exceptions reach only the processor's `backend_exception_handler`, so the harness re-raises them. Wrapped in `tests/helpers/reflex_harness.py`. The driver itself is still unit-tested through the `StateAccess` fake. | — |
| OQ-2 | ~~The exact command or API that compiles an example in CI without starting servers~~ **Resolved (T-040):** `reflex compile --dry` (Reflex 0.10.1) compiles every page without writing `.web` or installing the frontend, and needs no Node. CI runs it from the example directory with `AGENTKIT_MODEL=test`; the example's `rxconfig.py` then swaps PydanticAI's `models.infer_model` for one that returns `TestModel`, so the verbatim quickstart builds with no API key. Apps declare `rx.plugins.RadixThemesPlugin()`, because implicit Radix enablement is deprecated in 0.10.1. | — |
| OQ-3 | ~~`rx.markdown` raw-HTML default in 0.10.1 (DD-015)~~ **Resolved (T-036):** raw HTML is on by default; the library passes `use_raw=False` (DD-015). | — |
| OQ-4 | Report the ag-ui-langgraph `fastapi` import bug upstream | Before the LangGraph docs PR |

---

## Constitution Check

| Article | How this design complies |
|---|---|
| Art. 1 AG-UI canonical | Every path produces `ag_ui.core` events consumed by one reducer. The LangGraph override keeps standard interrupts. `core` has no `reflex`/extra imports, enforced by a CI job. |
| Art. 2 Python-only | Built-in components. `rx.match` for renderers. No JS. |
| Art. 3 Secrets / telemetry | ClassVars and the registry hold clients. `_conv` is backend-only. Secret-leak test (§6.2). No metrics export. |
| Art. 4 Non-blocking | Pump and queue (DD-003). Offloaded sync handlers. Responsiveness test. Bounded cancel latency, including cross-worker. |
| Art. 5 Pure reducer | Functional core (§5.2). Fixtures plus property tests (§8). |
| Art. 6–7 Testing / quality | Test-first on core. Coverage and strict-typing gates. One justified `type: ignore` (DD-007). |
| Art. 8 Stability | Amendments A-1…A-8 applied to the unreleased v1, keeping the quickstart at 23 lines. |
| Art. 9 Process | The upstream facts are verified and pinned with contract tests, not taken from memory. |
| **Exceptions requested** | None. |

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-10-30 | Ernesto Crespo (with Claude) | Initial version |
| 1.1 | 2026-10-30 | Ernesto Crespo (with Claude) | Analyze fixes: lazy top-level re-exports (A-01); gates on core and state (A-04); `AGENT_EXCEPTION` mapping (A-06); frontend-tool termination fact added to the contract tests (A-18). |
| 1.2 | 2026-10-31 | Ernesto Crespo (with Claude) | §8.4 item 4 refined while implementing T-004: on disconnect Reflex 0.10.1 cancels hydration and `on_load` chains only (spec drift rule). |
| 1.3 | 2026-10-31 | Ernesto Crespo (with Claude) | Flow C.3: `resume_entries` reads `conv.resume`, captured by `begin_run` (DM v1.6); found in T-015. |
| 1.4 | 2026-10-31 | Ernesto Crespo (with Claude) | §11 OQ-1 resolved by the T-024 spike: handlers are tested through Reflex's `BaseStateEventProcessor` over an in-memory state manager; §8 updated. |
| 1.5 | 2026-10-31 | Ernesto Crespo (with Claude) | §5.3 and Flow E: failures are logged at ERROR by error code and exception type only, with the traceback at DEBUG, so agent exception messages that quote user content never appear above DEBUG (REQ-027.2); found in T-026 (spec drift rule). |
| 1.6 | 2026-10-31 | Ernesto Crespo (with Claude) | Flows A and C, §5.3, §6.1: the background handler is `drive_run`, because Reflex 0.10.1 rejects private event handlers (`ValueError: Event handlers cannot be private`); it stays a no-op unless it claims `_pending_start`. DD-006: the configuration check runs before Reflex binds the class, so a missing `ClassVar` raises `ConfigurationError`. Found in T-029 (spec drift rule). |
| 1.7 | 2026-10-31 | Ernesto Crespo (with Claude) | DD-015 and §11 OQ-3 resolved: `rx.markdown` enables raw HTML by default in Reflex 0.10.1, so components pass `use_raw=False`. Found in T-036. |
| 1.8 | 2026-10-31 | Ernesto Crespo (with Claude) | §11 OQ-2 resolved by T-040: examples compile in CI with `reflex compile --dry` and the `AGENTKIT_MODEL=test` swap in `rxconfig.py`. |
| 1.9 | 2026-10-31 | Ernesto Crespo (with Claude) | DD-012: `run()` uses a per-run `clone()` (upstream keeps per-run state on the instance) and `STATE_SNAPSHOT` drops the `messages` and `tools` keys. Found in T-042 (spec drift rule). |
