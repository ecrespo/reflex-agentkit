# reflex-agentkit v0.1

## Product Requirements Document (PRD)

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo (`ecrespo`) |
| **Status** | `APPROVED` |
| **Version** | 1.2 |
| **Date** | 2026-10-30 |
| **Reviewers** | Ernesto Crespo |
| **Last updated** | 2026-10-30 |
| **Governed by** | [`specs/constitution.md`](../constitution.md) v1.1 |

---

## 1. Executive Summary

We are building **reflex-agentkit**, a Python library that turns any AG-UI-compatible agent
into a production web app in the same process and the same language as the agent. It is
for Python developers who build agents with LangGraph, PydanticAI or similar frameworks
and today must choose between Streamlit (a quick prototype that does not hold up in
production) and a separate Next.js/TypeScript frontend. The problem it solves is the
missing middle: streaming chat, visible tool calls, human approval and shared state, all
in Python, with no frontend toolchain.

v0.1 ships four things. The first is a protocol-level core: a pure AG-UI reducer, an
`AgentState` Reflex mixin, and HTTP and in-process clients. The second is a set of
Reflex-native components. The third is two thin adapters (PydanticAI and LangGraph). The
fourth is a set of Python ports of the AG-UI Dojo demos. Success is measured by a working
**30-line quickstart**, a listing in the AG-UI integrations table, and early adoption on
PyPI (§4).

## 2. Context and Problem

### 2.1 Current situation
The common Python agent stack is *LangGraph or PydanticAI + FastAPI + (Streamlit or
Next.js)*.
- **Streamlit** re-runs the whole script on every interaction and has no native
  bidirectional channel. Streaming tool calls, mid-run approvals and cancellation have to
  be worked around.
- **Next.js + CopilotKit / AG-UI JS client** is production-grade, but it adds a second
  language, a second build, a second deploy target, and JSON contracts that have to be
  kept in sync across the boundary.
- **AG-UI** has become the de facto agent↔UI event protocol. Spec 1.0 defines 31 event
  types in 8 families, plus standard interrupts. PydanticAI (v2) and LangGraph
  (`ag-ui-langgraph`) emit it natively. Every first-party AG-UI client is JS/TS.

### 2.2 Problem
A Python developer who has a working agent cannot ship a production-quality UI for it
without leaving Python. The demand is visible: `agentstage-ui` on PyPI explicitly
positions itself against Streamlit and Reflex. Reflex already provides the hard parts
(server-held state, a WebSocket to every client, background tasks, components as Python
objects). What it lacks is the agent layer.

### 2.3 Opportunity
Become **the Python/Reflex client of AG-UI**:
- Implement the protocol once, and every compliant backend works.
- Show parity with the AG-UI Dojo in Python.
- Get listed in AG-UI's, PydanticAI's and LangGraph's docs through upstream PRs.

## 3. Target Users

### Persona 1: Agent developer leaving Streamlit
- **Description:** a Python engineer who has a LangGraph or PydanticAI agent and a
  Streamlit demo that stakeholders liked.
- **Main need:** a real app (streaming, approvals, multi-user) without learning TypeScript.
- **Frequency:** daily while the app is being built.
- **Technical level:** high in Python, low to medium in frontend.

### Persona 2: Product engineer shipping an internal agent app
- **Description:** an engineer on a small team that deploys an agent for internal users
  (ops, support, analysts).
- **Main need:** safe tool execution (human approval), per-user isolation, keys kept on
  the server, deployable as one Reflex app.
- **Frequency:** weekly.
- **Technical level:** medium to high.

### Persona 3: AG-UI ecosystem integrator
- **Description:** a maintainer of an agent framework or AG-UI integration who needs a
  Python reference client for demos and conformance.
- **Main need:** a client that implements the spec faithfully and is easy to run in CI.
- **Frequency:** occasional.
- **Technical level:** high.

## 4. Objectives and Success Metrics

### 4.1 Project objectives

| Objective | Metric | Target | Deadline |
|---|---|---|---|
| Prove the 30-line promise | `examples/quickstart/app.py` non-blank, non-comment lines; CI compile check | ≤ 30 lines, green | v0.1.0 release |
| Be the Python client of AG-UI | Listing in the AG-UI integrations table | PR submitted at release; merged | submitted at v0.1.0; merged ≤ 3 months after |
| Upstream visibility | Docs PRs to PydanticAI and LangGraph | 2 PRs opened | ≤ 1 month after v0.1.0 |
| Early adoption | PyPI downloads (pypistats, last 30 days) | ≥ 2,000 / month | 3 months after v0.1.0 |
| Community signal | GitHub stars | ≥ 300 | 3 months after v0.1.0 |
| Quality | `core` line coverage; CI on 3.11–3.13 | ≥ 85 %; green | every release |

### 4.2 User objectives

| User objective | Indicator |
|---|---|
| Go from `pip install` to a streaming chat quickly | Following the README quickstart takes < 5 min with an API key in hand (measured by a fresh-env walkthrough before release) |
| Ship human-approved tool execution | The human-in-the-loop Dojo demo works with both adapters |
| Avoid frontend code | Zero `.js`/`.ts`/`.jsx`/`.tsx` files in the package and examples |

## 5. Scope

### 5.1 In scope (v0.1)
- [ ] `reflex_agentkit.core`: pure AG-UI reducer, `AgentState` mixin, `AgentClient` protocol, `HttpAGUIClient`, `InProcessAGUIClient`, token batching, cancellation, per-client thread isolation.
- [ ] Human-in-the-loop based on AG-UI standard interrupts: tool-call approval (approve / approve with edited args / reject) and generic interrupts.
- [ ] Client-side ("frontend") tools: Python handlers in the Reflex app that are advertised to the agent through `RunAgentInput.tools`.
- [ ] Tool renderer registry: custom Reflex rendering per tool name (backend tool rendering and tool-based generative UI).
- [ ] Shared state through `STATE_SNAPSHOT` / `STATE_DELTA` (RFC 6902), plus optional Pydantic validation.
- [ ] Components: `agent_chat`, `message_list`, `composer`, `tool_call_card`, `approval_dialog`, `run_status_bar`, `shared_state_panel`.
- [ ] Adapters (extras): `[pydantic-ai]`, `[langgraph]`.
- [ ] Examples: `quickstart/`, `pydantic_ai_dojo/`, `langgraph_dojo/` (5 Dojo demos each).
- [ ] Quality: tests, CI, release workflow, docs site, upstream integration PR drafts.

### 5.2 Out of scope (v0.1)
- Thread persistence and a thread sidebar (v0.2, SQLModel).
- Generative UI from a declarative spec (allow-listed component renderer) (v0.2).
- Predictive state updates and agentic generative UI demos (v0.2).
- The `reflex-assistant-ui` rendering backend (v0.2+).
- Rendering of `ACTIVITY_*`, `SUBAGENT_*` and `RAW` events (accepted and tolerated, not rendered; REQ-012).
- Authentication / authorization. This is the host app's responsibility; we document integration points only.
- Observability UI (`reflex-agentscope`) and MCP hosting (`reflex-mcphost`) (Constitution, Non-goals).
- Automatic retry of failed runs (a manual "retry" is a COULD, REQ-028).

### 5.3 Future considerations (design for, do not build)
- **EP-1 Generative UI:** CUSTOM events / tool results carry a UI spec validated against an allow-list. The tool renderer registry (REQ-019) is the extension point.
- **EP-2 Persistence:** the `ThreadStore` protocol seam behind `new_thread()` and thread loading. v0.1 ships only the in-memory behavior.
- **EP-3 Rendering backends:** components consume `AgentState` only through public vars, so an alternative renderer can replace them.
- **EP-4 Reasoning UI:** `REASONING_*` text is stored in v0.1 (REQ-011) so a v0.2 component can show it.

## 6. Resolved Open Questions (decisions)

These are the five open questions from the kickoff brief. Product-level decisions are
made here. Items marked **→ TD** have mechanics that the Technical Design must validate
against current Reflex and adapter versions without changing the decision.

### D-01 In-process vs. sidecar execution
**Decision:** in-process is the default and the quickstart path. The agent runs as an
asyncio task in the Reflex backend worker that received the event. "Sidecar" needs no
new mechanism: it means running the agent as its own AG-UI HTTP server and pointing
`HttpAGUIClient` at it. This is the documented path for CPU-heavy or synchronous agents
and for scaling agents independently of the UI.
**Constraints carried into requirements:** async agents only on the loop. Synchronous
work is offloaded (Constitution Art. 4, REQ-024). Cancellation must work in single-worker
mode and in multi-worker mode with a shared (Redis) state manager (REQ-007).
**→ TD:** verify how Reflex background tasks behave across workers and when a client
reconnects. Choose the cancel-signal mechanism (state flag polled at flush vs. task
registry).

### D-02 `thread_id` ↔ Reflex `client_token` ↔ AG-UI `threadId`
**Decision:** `thread_id` is a UUID4 that the library generates lazily on the first
`send_message`. It is stored in `AgentState` and sent verbatim as AG-UI `threadId`. It is
**not** derived from `client_token`: a client can start many threads, and v0.2
persistence must be able to reopen a thread from another session. A thread lives as long
as the Reflex state for that client lives. A page reload that keeps the same client token
keeps the thread, while a new tab gets a new state and therefore a new thread.
`new_thread()` rotates the ID. `run_id` is a new UUID4 for every run.
**→ TD:** confirm Reflex token lifetime across reload and reconnect in the pinned version.
Decide what happens to an in-flight run when its client disconnects (REQ-026).

### D-03 Approval UX and the edited-args contract
**Decision:** approvals and generic human-in-the-loop requests both use **AG-UI standard
interrupts**: `RUN_FINISHED` with `outcome.type == "interrupt"`, answered by the next
`RunAgentInput.resume[]`. Approving with edited args does **not** re-send the tool call.
It sends one `ResumeEntry` with
`payload = {"approved": true, "editedArgs": {...}}`. This is PydanticAI v2's native
contract (`Interrupt.reason == "tool_call"`, `Interrupt.id == "int-<tool_call_id>"`). The
LangGraph adapter adopts the same payload shape: it ships a helper that a graph calls in
place of a raw `interrupt()` for tool approval, and it enables the integration's
`emit_interrupt_outcome`. Generic (non-tool) interrupts expose the agent's payload as-is
in `pending_interrupt` and resume with whatever payload the app supplies.
**→ TD:** pin `ag-ui-protocol`, `pydantic-ai` and `ag-ui-langgraph` versions that support
`resume[]`. Decide whether to support the legacy LangGraph `on_interrupt` CUSTOM event as
a fallback (SHOULD, REQ-034.5).

### D-04 Shared-state typing
**Decision:** `shared_state` is always a JSON-compatible `dict[str, Any]` in the
Reflex state, because that is what serializes to the browser and what RFC 6902 patches
operate on. As an option, a developer may declare `shared_state_model: type[BaseModel]`.
When it is set, every snapshot and every patch result is validated before it is applied,
and a typed accessor is provided for server-side code (REQ-016).

### D-05 Dependencies and extras
**Decision:** `ag-ui-protocol` is a **hard dependency** because AG-UI is the canonical
model (Art. 1) and its types are used throughout `core`. `httpx` is a hard dependency
(it is already a transitive dependency of Reflex). A JSON Patch implementation is
chosen in the TD: a library or a small vendored module. Extras: `[pydantic-ai]`,
`[langgraph]`, `[all]`. No other extras in v0.1.

### D-06 Run status gains `awaiting_input`; tool status gains `rejected` *(deviation from the brief)*
The brief lists `run_status ∈ {idle, running, cancelled, error}` and
`tool status ∈ {streaming, pending_approval, running, done, error}`. Standard interrupts
create a state that neither list can express: the run has *finished*, but it is paused
waiting for a human. Rejection is also an outcome that is distinct from an error. So
`run_status` adds `awaiting_input`, and tool status adds `rejected`.
`pending_interrupt` remains the single current *generic* interrupt. Tool approvals live
on each tool call's status, because one `RUN_FINISHED` may carry several approvals.

---

## 7. Functional Requirements

**Conventions.** "THE SYSTEM" means the reflex-agentkit library running inside a host
Reflex app. "The developer" is the app author. "The user" is the person using the app in a
browser. Each criterion has a stable ID `REQ-NNN.k`, and tests cite these IDs
(Constitution Art. 6). Priorities follow MoSCoW. EARS keywords: WHEN (event), WHILE
(state), WHERE (option), IF…THEN (unwanted), none (ubiquitous).

### 7.1 Conversation and run lifecycle

#### REQ-001 — Send a message and start a run · `MUST`
- **Actor:** user (through `composer` or by calling `send_message(text)`).
- **Preconditions:** `run_status ∈ {idle, cancelled, error}`.
- **Postconditions:** a `user` message (the human's turn) is appended. A run is in progress with a new `run_id`.

1. WHEN the user sends non-empty text, THE SYSTEM SHALL append a `user` message (the human's turn) with that text to `messages` before the agent produces any event.
2. WHEN the user sends non-empty text, THE SYSTEM SHALL start a run whose `RunAgentInput` carries the current `thread_id`, a new UUID4 `run_id`, the full message history, the current `shared_state` and the registered client-side tools.
3. WHEN a run starts, THE SYSTEM SHALL set `run_status` to `running` and clear `error`.
4. IF the text is empty or whitespace-only, THEN THE SYSTEM SHALL ignore the call and leave `messages` and `run_status` unchanged.
5. IF the text exceeds the configured maximum length (default 32,000 characters), THEN THE SYSTEM SHALL reject it, leave `messages` unchanged, and set `error` to a message naming the limit.
6. IF `send_message` is called while `run_status == running`, THEN THE SYSTEM SHALL ignore the call and leave the active run unaffected.

#### REQ-002 — Thread identity · `MUST`
1. WHEN the first run of a thread starts and `thread_id` is empty, THE SYSTEM SHALL generate a UUID4 `thread_id` and send it as AG-UI `threadId`.
2. WHILE a thread is active, THE SYSTEM SHALL send the same `thread_id` on every run of that thread.
3. WHEN `new_thread()` is called while `run_status != running`, THE SYSTEM SHALL clear `messages`, `tool_calls`, `pending_interrupt`, `shared_state` and `error`, set `run_status` to `idle`, and assign a new `thread_id`.
4. IF `new_thread()` is called while `run_status == running`, THEN THE SYSTEM SHALL cancel the run (REQ-007) before resetting the thread.

#### REQ-003 — Per-client isolation · `MUST`
1. THE SYSTEM SHALL keep `messages`, `tool_calls`, `pending_interrupt`, `shared_state`, `run_status`, `thread_id`, `run_id` and `error` scoped to one Reflex client state, so that events from one client's run never change another client's state.
2. WHEN two browser clients run concurrently against the same agent, THE SYSTEM SHALL deliver each run's events only to the client that started it.

#### REQ-004 — Run completion · `MUST`
1. WHEN `RUN_FINISHED` arrives without an interrupt outcome and no client-side tool call is awaiting execution, THE SYSTEM SHALL set `run_status` to `idle`. (When client-side tool calls are awaiting execution, `run_status` stays `running` through the client-tool round, REQ-018.2.)
2. WHEN `RUN_FINISHED` arrives with `outcome.type == "interrupt"`, THE SYSTEM SHALL set `run_status` to `awaiting_input` and expose the interrupts (REQ-013, REQ-014).
3. WHEN `RUN_ERROR` arrives, THE SYSTEM SHALL set `run_status` to `error`, set `error` to the event's message, and keep all content streamed so far.
4. WHEN the upstream stream ends (EOF) without `RUN_FINISHED` or `RUN_ERROR`, THE SYSTEM SHALL set `run_status` to `error` with an "agent stream ended unexpectedly" message.

### 7.2 Streaming and the reducer

#### REQ-005 — Pure event reducer · `MUST`
1. THE SYSTEM SHALL expose `reduce(state, event) -> state`, a pure function with no I/O, no clock reads and no randomness, that is the only path by which AG-UI events change agent state (Constitution Art. 1, 5).
2. WHEN the same ordered event sequence is reduced twice from the same initial state, THE SYSTEM SHALL produce equal resulting states.
3. THE SYSTEM SHALL ship JSON Lines fixtures under `tests/fixtures/` covering every event type supported by REQ-010–REQ-012, including out-of-order and error sequences.

#### REQ-006 — Token batching · `MUST`
1. WHILE a run is streaming, THE SYSTEM SHALL apply events to the state immediately but push state updates to the client at most once per flush interval (default 50 ms, configurable per state class).
2. WHEN a run ends (finish, error, interrupt or cancel), THE SYSTEM SHALL flush any pending update immediately.
3. WHEN 1,000 `TEXT_MESSAGE_CONTENT` events arrive within 1 s with a 50 ms interval, THE SYSTEM SHALL push no more than 25 state updates for that second (a test asserts this against a counting fake).
4. WHERE the flush interval is configured to 0, THE SYSTEM SHALL push one update per event.

#### REQ-007 — Cancellation · `MUST`
1. WHEN `cancel_run()` is called while `run_status == running`, THE SYSTEM SHALL stop applying events from that run and set `run_status` to `cancelled` within 1 s.
2. WHEN a run is cancelled through `HttpAGUIClient`, THE SYSTEM SHALL close the upstream HTTP connection (a test asserts the fake server observes the disconnect).
3. WHEN a run is cancelled through `InProcessAGUIClient`, THE SYSTEM SHALL cancel the agent's asyncio task (a test asserts the agent observes `CancelledError`).
4. WHEN a run is cancelled, THE SYSTEM SHALL keep the partial assistant message and mark any `streaming` or `running` tool call as `error` with result "cancelled".
5. IF events of a cancelled run arrive after cancellation, THEN THE SYSTEM SHALL discard them.
6. WHERE the app runs multiple backend workers with a shared state manager, THE SYSTEM SHALL honor `cancel_run()` even when the cancel event is handled by a different worker than the one running the stream. → TD D-01. *(`SHOULD`; MUST for single-worker.)*

#### REQ-008 — Text messages · `MUST`
1. WHEN `TEXT_MESSAGE_START` arrives, THE SYSTEM SHALL append an `assistant` message with the event's `messageId`, empty content and `streaming = true`.
2. WHEN `TEXT_MESSAGE_CONTENT` arrives for a known message, THE SYSTEM SHALL append `delta` to that message's content.
3. WHEN `TEXT_MESSAGE_END` arrives, THE SYSTEM SHALL set that message's `streaming = false`.
4. WHEN `TEXT_MESSAGE_CHUNK` arrives, THE SYSTEM SHALL treat it as START (first chunk of an ID), CONTENT and, at run end, END, per the AG-UI chunk semantics.
5. IF `TEXT_MESSAGE_CONTENT` arrives for an unknown `messageId`, THEN THE SYSTEM SHALL create the assistant message implicitly, apply the delta, and record a warning in the reducer's diagnostics.
6. WHEN a run ends while a message is still `streaming`, THE SYSTEM SHALL set it to `streaming = false`.

#### REQ-009 — Tool call streaming · `MUST`
1. WHEN `TOOL_CALL_START` arrives, THE SYSTEM SHALL add a tool call with the event's `toolCallId` and `toolCallName`, empty args text, and status `streaming`, linked to its parent message if one is given.
2. WHEN `TOOL_CALL_ARGS` arrives, THE SYSTEM SHALL append the delta to the call's raw args text and expose the parsed args whenever the accumulated text is valid JSON.
3. WHEN `TOOL_CALL_END` arrives, THE SYSTEM SHALL set status `running` for backend tools, or hand the call to its client-side handler for registered client-side tools (REQ-018).
4. WHEN `TOOL_CALL_RESULT` arrives, THE SYSTEM SHALL store the result content on the call, set status `done`, and append a `tool` message.
5. WHEN `TOOL_CALL_CHUNK` arrives, THE SYSTEM SHALL apply it with the same semantics as START/ARGS/END per the AG-UI chunk rules.
6. IF `TOOL_CALL_ARGS`, `TOOL_CALL_END` or `TOOL_CALL_RESULT` arrives for an unknown `toolCallId`, THEN THE SYSTEM SHALL ignore it and record a warning.
7. IF a call's accumulated args are not valid JSON at `TOOL_CALL_END`, THEN THE SYSTEM SHALL keep the raw text, set status `error`, and set the result to an "invalid tool arguments" message.

#### REQ-010 — Lifecycle, step and snapshot events · `MUST`
1. WHEN `RUN_STARTED` arrives, THE SYSTEM SHALL record its `runId` as the active `run_id`.
2. IF an event arrives whose run is not the active run, THEN THE SYSTEM SHALL discard it.
3. WHEN `STEP_STARTED` arrives, THE SYSTEM SHALL expose the step name as `current_step`, and WHEN `STEP_FINISHED` arrives for that step, it SHALL clear `current_step`.
4. WHEN `MESSAGES_SNAPSHOT` arrives, THE SYSTEM SHALL replace `messages` with the snapshot's messages, keeping the tool call statuses of calls that are still present.
5. WHEN `CUSTOM` arrives, THE SYSTEM SHALL append `{name, value}` to a bounded `custom_events` list (default 100 most recent) and invoke any developer handler registered for that name (REQ-020).

#### REQ-011 — Reasoning events · `SHOULD`
1. WHEN `REASONING_MESSAGE_START/CONTENT/END/CHUNK` arrive, THE SYSTEM SHALL accumulate the reasoning text in a `reasoning` field attached to the run's assistant turn.
2. WHEN `REASONING_ENCRYPTED_VALUE` arrives, THE SYSTEM SHALL keep the opaque value server-side only, never render it, and send it back in later `RunAgentInput` messages as AG-UI requires.

#### REQ-012 — Unrendered, deprecated and unknown events · `MUST`
1. WHEN `ACTIVITY_SNAPSHOT`, `ACTIVITY_DELTA`, `SUBAGENT_STARTED`, `SUBAGENT_FINISHED`, `SUBAGENT_ERROR` or `RAW` arrives, THE SYSTEM SHALL leave the rendered state unchanged and continue the run.
2. IF an event has a type that is unknown to the installed `ag-ui-protocol` or that is deprecated (`THINKING_*`), THEN THE SYSTEM SHALL skip it, record a debug-level diagnostic, and continue the run.
3. IF an event fails AG-UI schema validation, THEN THE SYSTEM SHALL skip it, record a warning that includes the event type, and continue the run.

### 7.3 Human-in-the-loop

#### REQ-013 — Tool approval interrupts · `MUST`
1. WHEN `RUN_FINISHED` carries an interrupt with `reason == "tool_call"` and a `toolCallId`, THE SYSTEM SHALL set that tool call's status to `pending_approval` and attach the interrupt ID.
2. WHEN `approve_tool(call_id)` is called for a `pending_approval` call, THE SYSTEM SHALL record the answer `{"approved": true}` and set the call's status to `running`.
3. WHEN `approve_tool(call_id, edited_args)` is called with a dict, THE SYSTEM SHALL record `{"approved": true, "editedArgs": edited_args}` and show `edited_args` as the call's args.
4. WHEN `reject_tool(call_id, reason)` is called, THE SYSTEM SHALL record `{"approved": false, "reason": reason}` (reason omitted when `None`) and set the call's status to `rejected`.
5. WHEN every interrupt of the paused run has an answer, THE SYSTEM SHALL start the next run automatically, with `RunAgentInput.resume[]` holding one `ResumeEntry(status="resolved")` per interrupt, on the same `thread_id`.
6. IF `approve_tool` or `reject_tool` names a call that is not `pending_approval`, THEN THE SYSTEM SHALL ignore the call and leave the state unchanged.
7. IF `edited_args` is not a JSON object, THEN THE SYSTEM SHALL reject it, keep the call `pending_approval`, and set `error`.

#### REQ-014 — Generic interrupts · `MUST`
1. WHEN `RUN_FINISHED` carries an interrupt whose `reason` is not `"tool_call"`, THE SYSTEM SHALL expose it as `pending_interrupt` with its `id`, `reason`, message and payload.
2. WHEN `respond_to_interrupt(payload)` is called while `pending_interrupt` is set, THE SYSTEM SHALL record `ResumeEntry(status="resolved", payload=payload)` for it and clear `pending_interrupt`; when all interrupts have answers, REQ-013.5 applies.
3. IF several generic interrupts arrive in one `RUN_FINISHED`, THEN THE SYSTEM SHALL present them one at a time in arrival order through `pending_interrupt`.
4. IF `respond_to_interrupt` is called while `pending_interrupt` is `None`, THEN THE SYSTEM SHALL ignore the call.

#### REQ-015 — Leaving a paused run · `MUST`
1. WHILE `run_status == awaiting_input`, THE SYSTEM SHALL disable the composer and ignore `send_message`.
2. WHEN `cancel_run()` is called while `run_status == awaiting_input`, THE SYSTEM SHALL mark open approvals `rejected`, clear `pending_interrupt`, set `run_status` to `cancelled`, and remember the open interrupt IDs.
3. WHEN the next run starts after a cancelled pause, THE SYSTEM SHALL include a `ResumeEntry(status="cancelled")` for each remembered interrupt ID, so the agent's protocol state stays consistent.

### 7.4 Shared state

#### REQ-016 — Snapshot and delta · `MUST`
1. WHEN `STATE_SNAPSHOT` arrives, THE SYSTEM SHALL replace `shared_state` with the snapshot.
2. WHEN `STATE_DELTA` arrives, THE SYSTEM SHALL apply its RFC 6902 operations atomically to `shared_state`.
3. IF a delta fails to apply (bad path, failed `test` op), THEN THE SYSTEM SHALL leave `shared_state` unchanged, set `shared_state_stale = true`, record a warning, and continue the run.
4. WHEN a later `STATE_SNAPSHOT` arrives, THE SYSTEM SHALL clear `shared_state_stale`.
5. WHERE `shared_state_model` is set, THE SYSTEM SHALL validate each snapshot and each delta result against it, and on a validation failure SHALL apply 16.3's behavior.
6. WHERE `shared_state_model` is set, THE SYSTEM SHALL provide a typed accessor that returns a model instance for server-side code.
7. THE SYSTEM SHALL send the current `shared_state` as `RunAgentInput.state` on every run.

#### REQ-017 — App-side writes to shared state · `SHOULD`
1. WHEN the developer calls `set_shared_state(value)` or `patch_shared_state(ops)` while `run_status != running`, THE SYSTEM SHALL update `shared_state`, and the next run SHALL carry the new value.
2. IF a write is attempted while `run_status == running`, THEN THE SYSTEM SHALL reject it and set `error`, since the agent owns the state during a run.

### 7.5 Tools, rendering and extension points

#### REQ-018 — Client-side tools · `MUST`
1. WHERE the developer registers a client-side tool (name, description, JSON schema, async Python handler), THE SYSTEM SHALL advertise it in `RunAgentInput.tools` on every run.
2. WHEN the agent calls a registered client-side tool and the run finishes, THE SYSTEM SHALL execute the handler server-side with the parsed args, store its result on the tool call, set status `done`, and start a follow-up run that includes the tool result message.
3. WHERE a client-side tool is registered with `requires_approval=True`, THE SYSTEM SHALL set the call to `pending_approval` before running the handler and SHALL run it only after `approve_tool` (with edited args if given). On `reject_tool` it SHALL send a rejection result message instead.
4. IF a handler raises, THEN THE SYSTEM SHALL set the call's status to `error`, send the error text as the tool result, and continue the conversation.
5. IF a handler does not finish within its timeout (default 30 s), THEN THE SYSTEM SHALL treat it as raising a timeout error per 18.4.

#### REQ-019 — Tool renderer registry · `MUST`
1. WHERE the developer registers a renderer for a tool name, THE SYSTEM SHALL render tool calls with that name using the renderer (a Python function that returns a Reflex component given the tool call var) in place of the default `tool_call_card` body.
2. THE SYSTEM SHALL render calls with no registered renderer using the default `tool_call_card`.
3. THE SYSTEM SHALL resolve renderers at app compile time, using only Reflex built-in components and no custom JS (Constitution Art. 2).

#### REQ-020 — CUSTOM event handlers · `SHOULD`
1. WHERE the developer registers a handler for a CUSTOM event name, THE SYSTEM SHALL invoke it with the event value server-side, after the reducer has applied the event.
2. IF a handler raises, THEN THE SYSTEM SHALL record a warning and continue the run.

### 7.6 Clients and adapters

#### REQ-021 — `AgentClient` protocol and clients · `MUST`
1. THE SYSTEM SHALL define an `AgentClient` protocol: given a `RunAgentInput`, it yields AG-UI events asynchronously and supports cancellation.
2. WHEN `HttpAGUIClient` runs, THE SYSTEM SHALL POST the `RunAgentInput` to the configured URL with `Accept: text/event-stream` and decode each SSE event into an AG-UI event.
3. IF the HTTP endpoint returns a non-2xx status, THEN THE SYSTEM SHALL end the run with `run_status = error` and an `error` that contains the status code and no response headers.
4. IF the connection drops or the read timeout (configurable, default 60 s between events) expires mid-run, THEN THE SYSTEM SHALL end the run with `run_status = error`.
5. WHEN `InProcessAGUIClient` runs, THE SYSTEM SHALL obtain AG-UI events directly from an in-process AG-UI-compatible agent object, without HTTP serialization.
6. WHERE `HttpAGUIClient` is configured with headers (e.g., auth), THE SYSTEM SHALL send them upstream and SHALL NOT store them in any Reflex State var (Constitution Art. 3).

#### REQ-022 — PydanticAI adapter (`[pydantic-ai]`) · `MUST`
1. WHEN a `pydantic_ai.Agent` is wrapped by the adapter, THE SYSTEM SHALL drive it through PydanticAI's native AG-UI support and produce standard AG-UI events.
2. WHEN a tool with `requires_approval=True` is proposed, THE SYSTEM SHALL surface it as a `pending_approval` tool call (REQ-013) with no adapter-specific code in `core`.
3. WHEN the user approves with edited args, THE SYSTEM SHALL resume such that the tool executes with the edited args (verified by an integration test with a test model).
4. WHERE the wrapped agent has approval-required tools and its `output_type` does not include `DeferredToolRequests`, THE SYSTEM SHALL inject it at run time, so that a proposed approval-required call ends the run with an interrupt outcome and no user configuration is needed.

#### REQ-034 — LangGraph adapter (`[langgraph]`) · `MUST`
1. WHEN a compiled LangGraph graph is wrapped, THE SYSTEM SHALL drive it through the official `ag-ui-langgraph` integration with interrupt outcomes enabled.
2. WHEN the graph calls `interrupt(value)`, THE SYSTEM SHALL expose it as `pending_interrupt`, and `respond_to_interrupt(payload)` SHALL resume the graph with `payload` as the `Command(resume=...)` value.
3. WHEN the graph uses the adapter's approval helper for a tool call, THE SYSTEM SHALL expose it as `pending_approval`, and the helper SHALL return the decision, including edited args, to the graph.
4. THE SYSTEM SHALL require the wrapped graph to have a checkpointer, and IF it has none, THEN it SHALL raise a configuration error at wrap time.
5. WHERE the installed integration emits only the legacy `on_interrupt` CUSTOM event, THE SYSTEM SHOULD map it to `pending_interrupt` and resume through the legacy channel. → TD D-03. *(`SHOULD`.)*

### 7.7 Components

#### REQ-023 — Components · `MUST`
1. `agent_chat(state=S)` SHALL render a message list, composer, tool call cards, approval dialog and run status bar bound to `S`, with no further arguments needed.
2. `message_list` SHALL render user, assistant and tool messages in order, and show a streaming indicator on a message whose `streaming` is true.
3. `composer` SHALL submit on Enter and on button click, insert a newline on Shift+Enter, and be disabled WHILE `run_status ∈ {running, awaiting_input}`.
4. `tool_call_card` SHALL show the tool name, a status badge, and collapsible args and result sections.
5. `approval_dialog` SHALL open WHILE any tool call is `pending_approval` or `pending_interrupt` is set, and offer approve, edit-args (JSON editor with validation) and reject (optional reason) for approvals, or a developer-supplied form for generic interrupts (default: a JSON payload editor).
6. `run_status_bar` SHALL show the run status and `current_step`, a cancel button WHILE `run_status == running`, and `error` WHEN set.
7. `shared_state_panel` SHALL render `shared_state` as formatted JSON and show a "stale" marker WHILE `shared_state_stale` is true.
8. Every component SHALL accept standard Reflex style props and SHALL use only Reflex built-in components (Constitution Art. 2).
9. Every interactive control SHALL have an accessible label (aria-label or visible text) and be reachable by keyboard.

### 7.8 Robustness

#### REQ-024 — Non-blocking execution · `MUST`
1. WHILE a run is streaming, THE SYSTEM SHALL keep other clients of the same worker responsive: with a fake agent that does 2 s of blocking work per run (offloaded per Art. 4), a second client's simple event SHALL complete in < 200 ms.
2. WHERE an in-process agent exposes only a synchronous API, THE SYSTEM SHALL run it off the event loop (thread offload).

#### REQ-025 — Secret hygiene · `MUST`
1. THE SYSTEM SHALL keep `AgentClient` instances, agent objects, HTTP headers and adapter configuration out of every Reflex State var sent to the browser.
2. A test SHALL serialize the client-visible state of a configured example app after a full run and assert that it contains none of the configured header values or API key values.

#### REQ-026 — Disconnects · `SHOULD`
1. WHEN a client disconnects during a run, THE SYSTEM SHALL keep applying events to that client's state until the run ends, so that a reconnect with the same client state shows the completed result. → TD D-02.
2. IF the client's state has expired (state manager TTL), THEN THE SYSTEM SHALL cancel the run and close the upstream stream.

#### REQ-027 — Diagnostics · `SHOULD`
1. THE SYSTEM SHALL log through the standard `logging` module under the `reflex_agentkit` logger namespace, and SHALL include `thread_id` and `run_id` in every run-scoped log record.
2. THE SYSTEM SHALL NOT log message contents, tool args or tool results at levels above DEBUG.

#### REQ-028 — Retry last run · `COULD`
1. WHEN `retry_run()` is called while `run_status ∈ {error, cancelled}`, THE SYSTEM SHALL start a new run with the same messages up to the last `user` message.

### 7.9 Examples, packaging, quality and docs

#### REQ-029 — Quickstart · `MUST`
1. `examples/quickstart/` SHALL be ≤ 30 non-blank, non-comment lines, and SHALL demonstrate streaming chat, one visible tool call and one approval-required tool (Constitution Art. 8).
2. CI SHALL fail if the line limit is exceeded or the app does not compile.
3. The README SHALL contain the quickstart verbatim, and a test SHALL assert that the README block matches the file.

#### REQ-030 — Dojo examples · `MUST`
1. `examples/pydantic_ai_dojo/` and `examples/langgraph_dojo/` SHALL each implement: agentic chat, backend tool rendering, human-in-the-loop, shared state, and tool-based generative UI, each demo in 50–200 lines of Python.
2. Each example SHALL run with `reflex run`, and SHALL have a compile smoke test in CI that runs without network or API keys (test model / fake LLM).

#### REQ-031 — Packaging · `MUST`
1. THE SYSTEM SHALL be installable as `reflex-agentkit` (import `reflex_agentkit`), version `0.1.0`, `src/` layout, hatchling, with extras `[pydantic-ai]` (PydanticAI with the AG-UI support plus the `anthropic` and `openai` providers, so Claude works out of the box and Ollama works through its OpenAI-compatible API), `[langgraph]` (`ag-ui-langgraph[fastapi]` + `langgraph`) and `[all]`. Exact ranges: TD DD-001.
2. `import reflex_agentkit` and the `core` test suite SHALL succeed with no extras installed (Constitution Art. 1).
3. IF an adapter module is imported without its extra installed, THEN THE SYSTEM SHALL raise `ImportError` naming the `pip install reflex-agentkit[<extra>]` command.

#### REQ-032 — CI and release · `MUST`
1. CI SHALL run ruff (lint and format check), mypy (`--strict` on core), and pytest with coverage on Python 3.11, 3.12 and 3.13 for every PR and every push to `main`, and SHALL fail on any violation or on core coverage < 85 % (Constitution Art. 6, 7).
2. WHEN a `v*` tag is pushed, the release workflow SHALL build sdist and wheel and publish to PyPI through trusted publishing, with no stored API token.

#### REQ-033 — Documentation · `MUST`
1. The repo SHALL contain README (narrative, quickstart, feature table, comparison with Streamlit / CopilotKit / agentstage-ui), CONTRIBUTING, CHANGELOG (Keep a Changelog), `CLAUDE.md` and `AGENTS.md` that point to `specs/constitution.md`, and an MkDocs Material site under `docs/`.
2. `docs/integrations/` SHALL contain ready-to-submit drafts for: the AG-UI integrations table entry, a PydanticAI "UI with Reflex" page, and a LangGraph "frontend with Reflex" page.
3. The docs SHALL include a "sidecar deployment" guide (D-01) and a "security model" page that explains which data reaches the browser (REQ-025).

## 8. Non-Functional Requirements

| ID | Area | Requirement (verifiable) |
|---|---|---|
| NFR-01 | Performance | Library overhead from upstream event receipt to state applied: < 1 ms p95 per event (reducer micro-benchmark, 10k-event fixture). |
| NFR-02 | Performance | With the default 50 ms flush, ≤ 20 state pushes per second per client during streaming (REQ-006.3). |
| NFR-03 | Responsiveness | Cancel → `cancelled` visible ≤ 1 s (REQ-007.1); other clients' events < 200 ms during a run (REQ-024.1). |
| NFR-04 | Scalability | 20 concurrent clients streaming 50 tokens/s from a fake agent on one worker: no client's flush lag > 250 ms p95 (benchmark test, `SHOULD`). |
| NFR-05 | Security | Constitution Art. 3; REQ-021.6, REQ-025. No telemetry; no network calls other than configured agent endpoints. |
| NFR-06 | Compatibility | Python 3.11–3.13; Reflex, `ag-ui-protocol`, `pydantic-ai`, `ag-ui-langgraph` version ranges pinned in the TD and tested in CI. |
| NFR-07 | Maintainability | `mypy --strict` clean on `core`; core coverage ≥ 85 %; public API documented with docstrings. |
| NFR-08 | Accessibility | REQ-023.9; components keep Reflex/Radix default contrast in light and dark mode. |
| NFR-09 | Observability | REQ-027 (library logging only; tracing UI is a non-goal). |

## 9. Constraints and Dependencies

### Technical constraints
- Reflex-native components only; no custom React/JS (Constitution Art. 2, kickoff decision).
- AG-UI is the internal event model; adapters translate into it (Art. 1).
- Reflex State vars are serialized to the browser, so anything sensitive must live in backend-only storage (Art. 3).
- The Reflex event loop is shared by all clients of a worker (Art. 4).

### External dependencies

| Dependency | Type | Owner | Status | Risk |
|---|---|---|---|---|
| `reflex` | hard | Reflex Inc. | stable; version to pin in TD | Medium: background-task / state-manager semantics may change between minors |
| `ag-ui-protocol` (Python) | hard | AG-UI project | spec 1.0, 31 events, standard interrupts | Medium: fast-moving, and `resume[]` is recent |
| `httpx` | hard | Encode | stable | Low |
| JSON Patch implementation | hard | TD decides (library vs. vendored) | — | Low |
| `pydantic-ai` (≥ v2 with `AGUIAdapter`) | extra | Pydantic | v2.0.0 available | Medium: v2 is new |
| `ag-ui-langgraph` + `langgraph` | extra | AG-UI / LangChain | `emit_interrupt_outcome` is opt-in | Medium–High: interrupt outcome is newly standardized; legacy path still the default |

## 10. User Stories

### Epic E1: Chat with my agent
**US-001:** As an agent developer (P1), I want to wrap my agent and drop in `agent_chat`, so that I get a streaming chat in under 30 lines. → REQ-001, 004, 006, 008, 021, 023, 029
**US-002:** As a user, I want to stop a run that is going in the wrong direction, so that I do not wait for or pay for useless output. → REQ-007
**US-003:** As a user, I want to start a fresh conversation, so that earlier context does not leak into a new task. → REQ-002

### Epic E2: See and control tools
**US-004:** As a user, I want to see each tool call's name, args and result as it happens, so that I trust what the agent is doing. → REQ-009, 019, 023.4
**US-005:** As a product engineer (P2), I want dangerous tools to require approval, with the option to correct the args, so that the agent never acts without a human decision. → REQ-013, 015, 018.3, 022.2–3, 034.3
**US-006:** As an agent developer, I want my LangGraph `interrupt()` calls to become a UI prompt, so that I can build human-in-the-loop flows without custom plumbing. → REQ-014, 034.2

### Epic E3: Agent-driven UI
**US-007:** As an agent developer, I want the agent's state mirrored in the UI, so that I can show plans, progress or documents the agent maintains. → REQ-016, 017
**US-008:** As an agent developer, I want the agent to call a UI tool that renders a Reflex component, so that I can build tool-based generative UI. → REQ-018, 019

### Epic E4: Run it in production
**US-009:** As a product engineer, I want API keys to stay on the server and users isolated from each other, so that I can deploy to real users. → REQ-003, 021.6, 025
**US-010:** As a product engineer, I want to run the agent as a separate service when it is heavy, so that the UI stays responsive. → D-01, REQ-021.2, 024, 033.3
**US-011:** As an AG-UI integrator (P3), I want a spec-faithful Python client with fixtures, so that I can test my backend against it. → REQ-005, 010, 012, 021

## 11. UX Flow (textual wireframe)

```
┌───────────────────────────── agent_chat ─────────────────────────────┐
│ run_status_bar:  ● running · step "search_flights"        [Cancel]   │
├──────────────────────────────────────────────────────────────────────┤
│ message_list                                                         │
│   You: Book me a flight to Lisbon next Friday                        │
│   Assistant: Let me look that up… ▍                                  │
│   ┌ tool_call_card ─ search_flights ── [done] ───────────── ▾ ┐      │
│   │ args: {"to": "LIS", "date": "2026-11-06"}                 │      │
│   │ result: 3 options …                                       │      │
│   └───────────────────────────────────────────────────────────┘      │
│   ┌ tool_call_card ─ book_flight ── [pending approval] ───────┐      │
├──────────────────────────────────────────────────────────────────────┤
│ composer: [ disabled while awaiting approval              ] [Send]   │
└──────────────────────────────────────────────────────────────────────┘
   approval_dialog (modal):  book_flight {"flight": "TP1351", "seat": "12A"}
   [Approve]  [Edit args…]  [Reject ▾ reason]
```

## 12. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Reflex background-task semantics block cross-worker cancellation | Medium | High | D-01 TD spike first. REQ-007.6 is SHOULD, single-worker is MUST. Document the sidecar path. |
| `ag-ui-langgraph` keeps interrupt outcomes opt-in, or changes them | Medium | Medium | The adapter enables the flag explicitly. Legacy fallback REQ-034.5. Pin versions, plus a CI job against latest to detect drift. |
| AG-UI spec churn (31 events and growing) | High | Medium | Tolerant reducer (REQ-012). Fixtures per event. `ag-ui-protocol` pinned to a compatible range. |
| Token streaming floods the WebSocket | Medium | High | Batching (REQ-006) and the benchmark (NFR-04). |
| Per-tool-name renderers are hard with compile-time Reflex components | Medium | Medium | TD spike: `rx.match` over registered names. Fallback: the default card. |
| Quickstart creeps past 30 lines | Medium | High (brand promise) | CI line-count gate (REQ-029.2). API designed backward from the quickstart in the API Spec. |
| Scope creep toward a chat-widget library or tracing UI | Medium | Medium | Constitution non-goals. Delta-spec gate (Art. 9). |

## 13. Estimated Timeline (solo maintainer, part-time)

| Phase | Estimated duration | Deliverable |
|---|---|---|
| Spec & Design (API, TD, Data Model, Plan, Tasks, Analyze) | 1–2 weeks | Approved specs |
| Core (reducer + fixtures, AgentState, clients, HITL) | 3 weeks | `core` at ≥ 85 % coverage |
| Components + quickstart | 1.5 weeks | `agent_chat`, quickstart ≤ 30 lines |
| Adapters + Dojo examples | 2 weeks | 10 demos, smoke tests |
| Docs, CI/release, upstream PR drafts | 1 week | `v0.1.0` on PyPI |

---

## Constitution Check

| Article | How this PRD complies |
|---|---|
| Art. 1 AG-UI canonical | All state changes go through the reducer (REQ-005). Adapters emit standard AG-UI, including standard interrupts (D-03). Core runs with no extras (REQ-031.2). |
| Art. 2 Python/Reflex-native | Components use built-ins only (REQ-019.3, 023.8). No JS files (§4.2). Agents run server-side (D-01). |
| Art. 3 Secrets / telemetry | REQ-021.6 and REQ-025 (secret-leak test); NFR-05. Encrypted reasoning stays server-side (REQ-011.2). |
| Art. 4 Non-blocking | Batching (REQ-006), bounded cancellation (REQ-007), thread offload (REQ-024) and the second-client responsiveness test. |
| Art. 5 Pure reducer | REQ-005, with fixtures for every supported event and the out-of-order/error cases in REQ-008.5, 009.6, 010.2, 012. |
| Art. 6–7 Testing / quality | Every criterion has an ID for test citation. Coverage and CI gates in REQ-032. |
| Art. 8 API stability / DX | Quickstart gate (REQ-029). The 0.1.0 baseline defines the public API surface the API Spec will freeze. |
| Art. 9 Process | Deviations from the brief are recorded explicitly (D-06), not silently applied. |
| **Exceptions requested** | None. |

## Change History

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-10-30 | Ernesto Crespo (with Claude) | Initial version |
| 1.1 | 2026-10-30 | Ernesto Crespo (with Claude) | TD amendment A-8: extras contents in REQ-031.1 (Claude + Ollama providers; LangGraph `[fastapi]`). |
| 1.2 | 2026-10-30 | Ernesto Crespo (with Claude) | Analyze fixes: REQ-004.1 keeps `running` during client-tool rounds (A-02); REQ-022.4 rewritten as testable injection (A-03); "human message" → `user` message (A-10). |

## Approvals

| Role | Name | Date | Status |
|---|---|---|---|
| Product owner / Maintainer | Ernesto Crespo | 2026-10-30 | ☑ Approved |
