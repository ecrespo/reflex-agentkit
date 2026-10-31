# reflex-agentkit v0.1 — Data Model Specification

## Metadata

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo (`ecrespo`) |
| **Status** | `APPROVED` (2026-10-30) · `RELEASED` in `0.1.0` (2026-10-31) |
| **Version** | 1.11 |
| **Date** | 2026-10-30 |
| **PRD / API / TD** | [PRD v1.1](../prd/agentkit-v0.1.md) · [API v1.1](../api/agentkit-python-api-v1.md) · [TD v1.0](../technical/agentkit-architecture.md), all APPROVED |
| **Governed by** | [`specs/constitution.md`](../constitution.md) v1.0 |

> **Adaptation of the template.** v0.1 has **no database**. Its "storage" is:
> - the Reflex state manager (memory, disk or Redis), which pickles backend vars;
> - the WebSocket deltas, which carry public vars to the browser as JSON;
> - the JSON Lines test fixtures.
>
> "Tables" are therefore value types and aggregates. "Indexes" are in-memory lookup
> structures tied to hot paths. "Migrations" are pickle-compatibility rules. §9 sketches
> the v0.2 persistence schema (design only; not implemented in v0.1).

---

## 1. Model Overview

Three representations of one conversation:

```
          AG-UI events (ag_ui.core, camelCase on the wire)
                         │ reduce()
                         ▼
 ┌────────────────────────────────────────────────┐   pickled by the state manager
 │ ConversationState  (backend-only var `_conv`)  │── (memory | disk | Redis, TTL 3600 s)
 │  frozen, slots; the single source of truth     │
 └───────────────┬────────────────────────────────┘
                 │ project()  at every flush (TD DD-008)
                 ▼
 ┌────────────────────────────────────────────────┐   JSON in Reflex deltas
 │ Public vars (API §4.2)                         │── → browser
 │  messages, tool_calls, pending_interrupt, …    │
 └────────────────────────────────────────────────┘
                 ▲
                 │ RunInputBuilder  (egress, API §8.1)
          RunAgentInput (history, state, tools, resume) → agent
```

### Relationship diagram

```
ConversationState 1 ── * ChatMessage           (ordered; visible + hidden roles)
                  1 ── * ToolCall              (ordered by TOOL_CALL_START)
                  1 ── * ReasoningRecord       (each → 0..1 assistant ChatMessage)
                  1 ── * OpenInterrupt         (of the current pause only)
                  1 ── * InterruptAnswer       (keyed by interrupt id)
                  1 ── * CustomEventRecord     (bounded ring)
                  1 ── * Diagnostic            (transient; cleared after logging)
                  1 ── 1 ReducerConfig
ChatMessage(assistant) 1 ── * ToolCall          via ToolCall.parent_message_id / ChatMessage.tool_call_ids
ToolCall               1 ── 0..1 ChatMessage(tool)   via ChatMessage.tool_call_id
ToolCall               0..1 ── 1 OpenInterrupt  via OpenInterrupt.tool_call_id = ToolCall.id
```

## 2. Representation rules (all types)

| Rule | Detail | Verified |
|---|---|---|
| R-1 | Every value type is `@dataclass(frozen=True, slots=True)` in `reflex_agentkit.core`. | 2026-10-30 spike: renders in `rx.foreach`, serializes, pickles |
| R-2 | Collections inside values are `tuple[...]`, never `list`. Mappings are `dict` but **never mutated after construction**: every change builds a new dict. Enforced by review, plus a property test that deep-copies before and after `reduce()` and compares the input. | — |
| R-3 | Enums are `enum.StrEnum`, so they serialize to their string value in Reflex deltas (`"done"`, not `"ToolCallStatus.DONE"`). | spike: `json_dumps` → `"status": "done"` |
| R-4 | JSON-typed payloads (`args`, `shared_state`, interrupt `payload`, CUSTOM `value`) are typed `JsonValue` = `None \| bool \| int \| float \| str \| list[JsonValue] \| dict[str, JsonValue]` (a `TypeAlias`). For dict-only fields, `JsonObject = dict[str, JsonValue]`. | — |
| R-5 | The same core value types are used as Reflex var types (`list[ChatMessage]`, `PendingInterrupt \| None`), with no parallel "view" classes. Public var types: list vars hold tuples converted with `list(...)` at projection, because Reflex var annotations are `list[...]`. | spike |
| R-6 | Field names are `snake_case`. AG-UI's camelCase exists only at the wire boundary, handled by `ag_ui.core` (pydantic aliases). | — |
| R-7 | IDs are `str`. Library-generated IDs are canonical UUID4 strings (`str(uuid.uuid4())`), matching AG-UI examples. Agent-provided IDs are kept verbatim. | — |

## 3. Entities

### 3.1 `ChatMessage` (public; API §5.1)

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | `str` | — | AG-UI `messageId` |
| `role` | `MessageRole` | — | StrEnum: `user`, `assistant`, `tool`, `system`, `developer` |
| `content` | `str` | `""` | Accumulated text |
| `streaming` | `bool` | `False` | |
| `tool_call_ids` | `tuple[str, ...]` | `()` | assistant only |
| `tool_call_id` | `str \| None` | `None` | tool only |
| `reasoning` | `str` | `""` | assistant only. A **projection copy** of the linked `ReasoningRecord.content`, filled by `project()`. Always `""` inside `ConversationState`. |
| `is_error` | `bool` | `False` | tool only. AG-UI `ToolMessage.error` is set, or a client-tool handler failed. |

**Visibility:** `system` and `developer` messages exist in `ConversationState` (they can
arrive in `MESSAGES_SNAPSHOT` and must be re-sent in the history), but `project()`
filters them out. The public `messages` var therefore only ever contains `user`,
`assistant` and `tool`, as API §5.1 promises. *Clarification, not an API change:* the
public type's `role` field is the full enum, but projected values are limited to those
three.

### 3.2 `ToolCall` (public; API §5.2)

| Field | Type | Default | Notes |
|---|---|---|---|
| `id` | `str` | — | AG-UI `toolCallId` |
| `name` | `str` | — | |
| `args_text` | `str` | `""` | Raw concatenated deltas. Capped at 1 MiB; beyond that the call goes to `error` "arguments too large". |
| `args` | `JsonObject \| None` | `None` | Parsed when `args_text` is valid JSON (re-parsed at most once per flush, not per delta; §5 H-3). Replaced by `editedArgs` on an approval with edits. |
| `status` | `ToolCallStatus` | `streaming` | |
| `result` | `str \| None` | `None` | |
| `parent_message_id` | `str \| None` | `None` | |
| `interrupt_id` | `str \| None` | `None` | Agent interrupt ID, or `local-<call_id>` for client-tool approvals (never sent upstream) |
| `is_client_tool` | `bool` | `False` | `name in config.client_tool_names` at `TOOL_CALL_START` |

### 3.3 `PendingInterrupt` (public; API §5.3)

Projection of the first unanswered **generic** `OpenInterrupt`:
`id`, `reason`, `message`, `payload: JsonValue`, `response_schema: JsonObject | None`,
`queue_position: int`, `queue_size: int`. It is never stored. It is computed by
`project()`.

### 3.4 `OpenInterrupt` (internal)

One per `Interrupt` in the `RUN_FINISHED(outcome=interrupt)` that paused the current
run, plus local entries for client-tool approvals.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | `Interrupt.id` (PydanticAI: `int-<tool_call_id>`), or `local-<call_id>` |
| `reason` | `str` | `"tool_call"` for approvals |
| `message` | `str` | `""` if absent |
| `tool_call_id` | `str \| None` | Set for `reason == "tool_call"` |
| `payload` | `JsonValue` | For LangGraph, `metadata["langgraph"]["raw"]`; else `None` |
| `response_schema` | `JsonObject \| None` | |
| `is_local` | `bool` | True for client-tool approvals (answered locally, never in `resume[]`) |

### 3.5 `InterruptAnswer` (internal)

| Field | Type | Notes |
|---|---|---|
| `interrupt_id` | `str` | |
| `status` | `Literal["resolved", "cancelled"]` | Mirrors `ResumeStatus` |
| `payload` | `JsonValue` | §7.4 contract of the API Spec |

### 3.6 `ReasoningRecord` (internal; REQ-011)

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Reasoning message ID from `REASONING_MESSAGE_START` / `ReasoningMessage.id` |
| `assistant_message_id` | `str \| None` | The assistant message of the same turn: the next `TEXT_MESSAGE_START` in the run, or the previous one if none follows |
| `content` | `str` | Accumulated text |
| `encrypted_value` | `str \| None` | From `REASONING_ENCRYPTED_VALUE`. **Never projected** (Art. 3). Re-sent as `ReasoningMessage(encrypted_value=…)` by `RunInputBuilder`. |

### 3.7 `CustomEventRecord` (public; API §5.4)

`name: str`, `value: JsonValue`, `run_id: str`.

### 3.8 `Diagnostic` (public, transient; API §11)

`level: Literal["debug", "warning"]`, `code: DiagnosticCode` (StrEnum, §6),
`message: str`, `event_type: str | None`.

### 3.9 `ReducerConfig` (internal)

`client_tool_names: frozenset[str]`, `custom_events_limit: int`,
`max_args_bytes: int = 1_048_576`. It is built once per run from the `AgentState`
ClassVars. It lives inside `ConversationState` so that `reduce` keeps its two-argument
signature (API §11).

### 3.10 `ConversationState` (internal aggregate; backend var `_conv`)

| Field | Type | Initial | Owner (TD DD-004) |
|---|---|---|---|
| `schema_version` | `int` | `1` | — (§8) |
| `thread_id` | `str` | `""` | `begin_run`, `new_thread` |
| `run_id` | `str` | `""` | `begin_run` |
| `run_status` | `RunStatus` | `idle` | reducer and commands |
| `error` | `str` | `""` | reducer and commands |
| `error_code` | `ErrorCode \| None` | `None` | reducer and commands |
| `current_step` | `str` | `""` | reducer |
| `messages` | `tuple[ChatMessage, ...]` | `()` | reducer, `begin_run`, `apply_client_tool_result` |
| `tool_calls` | `tuple[ToolCall, ...]` | `()` | reducer and commands |
| `reasoning` | `tuple[ReasoningRecord, ...]` | `()` | reducer |
| `shared_state` | `JsonObject` | `{}` | reducer, `set/patch_shared_state` |
| `shared_state_stale` | `bool` | `False` | reducer |
| `interrupts` | `tuple[OpenInterrupt, ...]` | `()` | reducer (on pause), commands (cleared on `begin_run`) |
| `answers` | `dict[str, InterruptAnswer]` | `{}` | commands |
| `abandoned_interrupt_ids` | `tuple[str, ...]` | `()` | `apply_cancel` while paused **moves the non-local interrupt IDs here and clears `interrupts` and `answers`** (local client-tool approvals are dropped); consumed by the next `begin_run` (REQ-015.3, keeps INV-4) |
| `resume` | `tuple[InterruptAnswer, ...]` | `()` | `begin_run`. The `RunAgentInput.resume` entries of the current run, captured from `answers` (non-local, in interrupt order) and `abandoned_interrupt_ids` (as `cancelled`) before `begin_run` clears `interrupts`, `answers` and `abandoned_interrupt_ids`. Read by `RunInputBuilder` through `commands.resume_entries` (the driver builds the input after `begin_run`, TD Flow A.4/C.3). Never projected. |
| `custom_events` | `tuple[CustomEventRecord, ...]` | `()` | reducer (ring of `config.custom_events_limit`) |
| `client_tool_rounds` | `int` | `0` | driver via commands (reset by a user-initiated `begin_run`) |
| `last_run_ids` | `tuple[str, ...]` | `()` | `begin_run`. Run IDs of this turn; events from older runs are discarded (REQ-010.2). |
| `diagnostics` | `tuple[Diagnostic, ...]` | `()` | reducer; cleared by the driver after logging |
| `dirty_tool_args` | `frozenset[str]` | `frozenset()` | reducer adds on `TOOL_CALL_ARGS`; `project()` parses and clears (H-3) |
| `config` | `ReducerConfig` | — | `begin_run` |
| `_tool_index` | `dict[str, int]` | `{}` | derived: tool call ID → position in `tool_calls` |
| `_message_index` | `dict[str, int]` | `{}` | derived: message ID → position in `messages` |

The derived indexes are rebuilt by the constructor helper `ConversationState.with_(...)`,
never set by hand. They are excluded from equality (`field(compare=False)`) and from the
pickled state (§8).

## 4. Invariants (each becomes a property test, TD §8)

| ID | Invariant |
|---|---|
| INV-1 | IDs are unique within `messages`, within `tool_calls`, within `interrupts` and within `reasoning`. |
| INV-2 | `_tool_index[c.id] == i` for every `(i, c)` in `tool_calls`; the same holds for `_message_index`. |
| INV-3 | Every `ChatMessage(role=tool).tool_call_id` names an existing `ToolCall`. Every ID in an assistant message's `tool_call_ids` names an existing `ToolCall`. |
| INV-4 | `run_status == awaiting_input` ⇔ `interrupts` is non-empty and at least one interrupt has no entry in `answers`. |
| INV-5 | `run_status != running` ⇒ no message has `streaming == True` and no tool call has status `streaming`. |
| INV-6 | A tool call has status `pending_approval` ⇒ its `interrupt_id` is set and names an entry in `interrupts` with no answer. |
| INV-7 | `answers` keys ⊆ `{i.id for i in interrupts}`. |
| INV-8 | `error_code` is a run-level code (`AGENT_*`, `CLIENT_TOOL_LOOP_LIMIT`) ⇒ `run_status == error`. Non-fatal codes (`MESSAGE_TOO_LONG`, `INVALID_EDITED_ARGS`, `SHARED_STATE_*`) may overwrite `error_code` under any status without changing it. |
| INV-9 | `len(custom_events) ≤ config.custom_events_limit`. |
| INV-10 | `shared_state` is JSON-serializable (round-trips through `json.dumps`/`loads` unchanged). Where `shared_state_model` is set, it also validates (checked by the state layer, which owns the model). |
| INV-11 | `ReasoningRecord.encrypted_value` never appears in any projected public var (secret-hygiene test, REQ-025). |
| INV-12 | `reduce` never mutates its input (R-2). |

## 5. Hot paths ("critical queries") and their structures

| ID | Operation | Frequency | Structure | Cost |
|---|---|---|---|---|
| H-1 | Append a text delta to the message with a given ID (`TEXT_MESSAGE_CONTENT`) | Every token (hundreds/s) | `_message_index` → position; replace one tuple slot | O(1) lookup + O(n) tuple copy (n = messages); str concat O(len) |
| H-2 | Append an args delta to a tool call (`TOOL_CALL_ARGS`) | Every args token | `_tool_index` | same as H-1 |
| H-3 | Parse `args_text` → `args` | At `TOOL_CALL_END`, and at most once per flush while streaming (for live display) | Lazy: the reducer adds the call ID to `dirty_tool_args`; `project()` parses those calls and clears the set | O(len) per flush, not per delta |
| H-4 | Find tool calls by interrupt ID (approval commands) | Per user action | Linear scan of `tool_calls` (n small) | O(n) |
| H-5 | Projection to public vars | Per flush (≤ 20/s) | Full rebuild of lists; Reflex diffs per var | O(messages + tool_calls) |
| H-6 | Build `RunAgentInput.messages` | Per run | Linear | O(history) |

**Performance budget check:** NFR-01 (< 1 ms p95 per event) is benchmarked with a
fixture of 500 messages and 10,000 content deltas. **Escape hatch, if it fails:** store
in-flight text as `tuple[str, ...]` chunks and join them at projection. This is internal
and does not change the API.

## 6. Enumerations (normative values)

| Enum | Values |
|---|---|
| `MessageRole` | `user`, `assistant`, `tool`, `system`, `developer` |
| `RunStatus` | `idle`, `running`, `awaiting_input`, `cancelled`, `error` |
| `ToolCallStatus` | `streaming`, `pending_approval`, `running`, `done`, `rejected`, `error` |
| `ErrorCode` | `MESSAGE_TOO_LONG`, `AGENT_RUN_ERROR`, `AGENT_HTTP_ERROR`, `AGENT_STREAM_ERROR`, `AGENT_EXCEPTION`, `INVALID_EDITED_ARGS`, `SHARED_STATE_LOCKED`, `SHARED_STATE_INVALID`, `SHARED_STATE_PATCH_FAILED`, `CLIENT_TOOL_LOOP_LIMIT` |
| `DiagnosticCode` | `UNKNOWN_EVENT_TYPE`, `INVALID_EVENT`, `IMPLICIT_MESSAGE`, `UNKNOWN_MESSAGE_ID`, `UNKNOWN_TOOL_CALL_ID`, `DUPLICATE_ID`, `STALE_RUN_EVENT`, `PATCH_FAILED`, `ARGS_TOO_LARGE`, `IGNORED_EVENT`. Commands reuse `IGNORED_EVENT` (level `warning`) for an interrupt response that is dropped because it exceeds 64 KiB serialized or is not JSON-encodable (TD §6). |

`ErrorCode` values are their own names, uppercase (`ErrorCode.MESSAGE_TOO_LONG == "MESSAGE_TOO_LONG"`).
The other enums use lowercase values as listed.

## 7. Mappings

### 7.1 AG-UI ingress (events → `ConversationState`)

| AG-UI | Internal effect (summary; full rules in PRD REQ-008…016) |
|---|---|
| `RunStartedEvent.run_id` | must be in `last_run_ids`; otherwise `STALE_RUN_EVENT` and the event is skipped |
| `TextMessageStart/Content/End/Chunk` | `ChatMessage(role=assistant)`; a CHUNK without a known ID creates one |
| `ToolCallStart/Args/End/Chunk` | `ToolCall`; the parent message's `tool_call_ids` is updated |
| `ToolCallResultEvent` | `ToolCall.result`, `status=done` (a `rejected` or `error` call keeps its terminal status, API §4.6), and a new `ChatMessage(role=tool, tool_call_id=…)` (deduplicated by `message_id` if present). AG-UI 1.0 `content` may be a list of multimodal parts: v0.1 flattens it to text (text parts concatenated, other parts as `[<type>]` placeholders), so multimodal results are not re-sent to the agent. |
| `StateSnapshot` / `StateDelta` | `shared_state` / `_patch.apply` (atomic). A failed delta sets `shared_state_stale`, `error_code=SHARED_STATE_PATCH_FAILED` and a `PATCH_FAILED` warning. A snapshot that is not a JSON object is rejected the same way with `SHARED_STATE_INVALID` and an `INVALID_EVENT` warning. |
| `MessagesSnapshot` | rebuild `messages` from AG-UI messages (§7.3); keep `ToolCall` records whose IDs still appear (a kept record with no `result` yet takes the one from the matching `tool` message, as `ToolCallResultEvent` does: `done` or `error`, and a `rejected` call keeps its status; a kept record whose streamed `args_text` is empty takes the snapshot's `function.arguments` when they parse to an object, keeping its status), drop the others, and create records (args parsed, result from the matching `tool` message) for calls known only from the snapshot; `reasoning` messages become `ReasoningRecord`s linked like streamed ones, and streamed records of surviving assistant messages are kept; `activity` messages are skipped; repeated IDs (`DUPLICATE_ID`) and `tool` messages for unknown calls (`UNKNOWN_TOOL_CALL_ID`) are dropped with warnings; rebuild the indexes |
| `ReasoningMessage*`, `ReasoningEncryptedValue` | `ReasoningRecord`. `ReasoningEncryptedValue` (AG-UI 1.0: `subtype` ∈ {`message`, `tool-call`}, `entity_id`) is kept only when it targets a reasoning message; values for tool calls or other messages are not retained in v0.1 (`IGNORED_EVENT`, debug). |
| `CustomEvent` | `CustomEventRecord` (ring) |
| `StepStarted/Finished` | `current_step` |
| `RunFinished(outcome)` | `success`/absent → `idle`, **unless** client-tool calls are awaiting execution (calls with `is_client_tool` in `running`, or the IDs in `outcome.pending_tool_call_ids` when present), in which case `running` is kept for the client-tool round (PRD REQ-004.1, REQ-018.2); `interrupt` → `interrupts` + `awaiting_input` (and the matching tool calls → `pending_approval`); `cancelled` → `cancelled` |
| `RunError` | `error`, `error_code=AGENT_RUN_ERROR` |
| `Activity*`, `Subagent*`, `Raw` | `IGNORED_EVENT` debug diagnostic only |

### 7.2 Projection (`ConversationState` → public vars)

| Public var | Source |
|---|---|
| `messages` | `[m for m in conv.messages if m.role in {user, assistant, tool}]`, with `reasoning` filled from the linked `ReasoningRecord.content` |
| `tool_calls` | `list(conv.tool_calls)` |
| `pending_interrupt` | the first `OpenInterrupt` with `tool_call_id is None` (not an approval), `not is_local` and no answer → `PendingInterrupt(queue_position, queue_size)`; else `None`. An interrupt is an approval exactly when it names a known tool call; a `tool_call` interrupt for an unknown call is stored with `tool_call_id=None` so it stays answerable. |
| `shared_state`, `shared_state_stale`, `run_status`, `current_step`, `thread_id`, `run_id`, `error`, `error_code` | same-named fields |
| `custom_events` | `list(conv.custom_events)` |
| *(never projected)* | `reasoning[*].encrypted_value`, `interrupts`, `answers`, `abandoned_interrupt_ids`, `resume`, `client_tool_rounds`, `last_run_ids`, `diagnostics`, `dirty_tool_args`, `config`, indexes |

### 7.3 AG-UI egress (`ConversationState` → `RunAgentInput.messages`)

| Internal | AG-UI message |
|---|---|
| `ChatMessage(user)` | `UserMessage(id, content)` |
| `ChatMessage(system/developer)` | `SystemMessage` / `DeveloperMessage` (verbatim) |
| `ReasoningRecord` with `encrypted_value` or content | `ReasoningMessage(id, content, encrypted_value)`, placed immediately before its assistant message |
| `ChatMessage(assistant)` | `AssistantMessage(id, content or None, tool_calls=[ToolCall(id, type="function", function={name, arguments=json.dumps(args or {})})])`. Uses the **edited** args if an approval edited them. |
| `ChatMessage(tool)` | `ToolMessage(id, tool_call_id, content, error=…)` when `is_error` |
| `abandoned_interrupt_ids` + `answers` (non-local) | `resume=[ResumeEntry(interrupt_id, status, payload)]` |

The round-trip property *ingress(MESSAGES_SNAPSHOT(egress(conv))) ≅ conv.messages* (modulo
streaming flags) is a property test.

## 8. Serialization and compatibility ("migrations")

| Channel | Format | Compatibility rule |
|---|---|---|
| Browser (public vars) | Reflex `json_dumps` of dataclasses, StrEnums and tuples | Public field names are API (Art. 8). They can be added, but not renamed or removed without deprecation. |
| State manager (`_conv`) | `pickle`, through the Reflex state manager (Redis keeps it for ≤ 3600 s by default) | **Every value type pickles through the shared `TolerantPickle` mixin:** its `__reduce__` emits `{"schema_version": n, **fields}` (derived fields excluded) and restores through a tolerant constructor (`_from_state`): missing fields take their defaults and unknown fields are dropped. After a library upgrade, a live Redis session with an older pickle therefore loads instead of crashing the user's session. *Why `__reduce__` and not `__setstate__`:* `@dataclass(frozen=True, slots=True)` installs its own `__getstate__`/`__setstate__` on each class (CPython 3.11–3.13), which would silently shadow a mixin's; `__reduce__` is not touched. `ConversationState` rebuilds its derived indexes after restore. A test pickles a v1 state, removes a field from the payload, adds an unknown one, and asserts that the state loads. |
| Test fixtures | JSON Lines (§10) | Fixtures are versioned with the code and never rewritten silently. A behavior change requires updating the expected header in the same PR, citing the delta spec. |

`schema_version` is bumped only when the meaning of an existing field changes (not when a
field is added). `__setstate__` holds the explicit upgrade steps from older versions.

## 9. v0.2 persistence (design for, do not build — PRD EP-2)

The seam: a `ThreadStore` protocol (v0.2), with `load(thread_id) -> ConversationState | None`,
`save(conv) -> None`, and `list_threads(owner_key, limit, before) -> list[ThreadSummary]`.
v0.1 behaves like an in-memory store that is implicitly the Reflex state.

Sketch of the SQLModel schema (non-normative):

| Table `agentkit_thread` | Type | Notes |
|---|---|---|
| `id` | `str` PK | = `thread_id` |
| `owner_key` | `str` | Supplied by the host app (user ID); agentkit does not do auth |
| `title` | `str` | First user message, truncated to 80 chars |
| `conversation` | JSON | `ConversationState.__getstate__()` JSON-encoded, **minus** `encrypted_value`s unless the host opts in |
| `schema_version` | `int` | |
| `created_at`, `updated_at` | `datetime` (UTC) | |
| Index `(owner_key, updated_at DESC)` | — | For the thread sidebar query "latest N threads of a user" |

Storing the aggregate as one JSON document (instead of normalized message rows) follows
from the access pattern: a whole thread is always loaded and saved together, and querying
individual messages is a non-goal. Revisit this if search over messages becomes a
requirement.

## 10. Test fixture format (JSON Lines; Constitution Art. 5)

`tests/fixtures/events/<scenario>.jsonl`:

```jsonl
{"fixture": "tool_call_happy_path", "reqs": ["REQ-009.1", "REQ-009.2", "REQ-009.4"], "config": {"client_tool_names": []}, "start": {"user_text": "weather in Lisbon?"}, "expect": {"run_status": "idle", "tool_calls": [{"name": "get_weather", "status": "done", "args": {"city": "Lisbon"}}], "messages.length": 3, "diagnostics.codes": []}}
{"type": "RUN_STARTED", "threadId": "$thread", "runId": "$run"}
{"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "get_weather", "parentMessageId": "m1"}
{"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": "{\"city\": \"Lis"}
{"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": "bon\"}"}
{"type": "TOOL_CALL_END", "toolCallId": "c1"}
{"type": "TOOL_CALL_RESULT", "toolCallId": "c1", "messageId": "t1", "content": "sunny"}
{"type": "RUN_FINISHED", "threadId": "$thread", "runId": "$run"}
```

- **Line 1, header:** `fixture` (name), `reqs` (the criteria it verifies, cited by the
  test), `config` (a `ReducerConfig` subset), `start` (applied with `begin_run` before the
  events), and `expect`. `expect` is a **partial match** on the projection: dotted
  paths, plus `.length`, plus `diagnostics.codes` (the diagnostic codes emitted during
  the replay, collected before clearing).
- **Event lines:** AG-UI wire JSON (camelCase), validated through `ag_ui.core` before
  `reduce()`. Lines that fail validation exercise REQ-012.3, with the expected
  `INVALID_EVENT` in `diagnostics.codes`.
- **Command lines:** `{"$command": "approve_tool", "call_id": "c1", "edited_args": {...}}`
  call the pure command functions, so human-in-the-loop scenarios replay too.
- **Placeholders:** `$thread`, `$run` and `$run2` are substituted with the IDs that
  `begin_run` assigned.
- **Recording:** a dev script `scripts/record_fixture.py` (TD tasks) captures real event
  streams from the PydanticAI and LangGraph adapters with test models, and writes this
  format. Recorded fixtures are reviewed and trimmed by hand before commit.

## 11. Archiving, backup, recovery

Not applicable in v0.1. State lives only as long as the Reflex state manager keeps it
(TD DD-014). The docs say so plainly: "a thread is lost when the session expires, until
v0.2 persistence."

---

## Constitution Check

| Article | Compliance |
|---|---|
| Art. 1 | Ingress and egress map only AG-UI types (§7). There is no framework-specific field in the model; LangGraph data is kept only as the opaque `OpenInterrupt.payload`. |
| Art. 3 | The never-projected list (§7.2) and INV-11 keep encrypted reasoning and internal answers out of the browser. |
| Art. 5 | Frozen values, the no-mutation invariant (INV-12), and a fixture format with REQ citations and command replay (§10). |
| Art. 8 | Public field names are API. The tolerant pickle (§8) prevents an upgrade from breaking live sessions. |
| **Exceptions requested** | None. |

## Change History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-10-30 | Initial version |
| 1.1 | 2026-10-30 | Analyze fixes: cancel-while-paused clears interrupts (A-05); INV-8 one-directional (A-07); `AGENT_EXCEPTION` (A-06); RUN_FINISHED keeps `running` for client-tool rounds (A-02). |
| 1.2 | 2026-10-31 | §8 tolerant pickling via `TolerantPickle.__reduce__` + `_from_state` instead of `__setstate__` (frozen slots dataclasses override a mixin's `__setstate__`); found in T-006 (spec drift rule). |
| 1.3 | 2026-10-31 | §7.1 `TOOL_CALL_RESULT` multimodal content is flattened to text in v0.1; found in T-012 (spec drift rule). |
| 1.4 | 2026-10-31 | §7.1 precise ingress rules for `MESSAGES_SNAPSHOT`, `REASONING_ENCRYPTED_VALUE` (AG-UI 1.0 `subtype`/`entity_id`; non-reasoning targets not retained in v0.1) and non-object `STATE_SNAPSHOT`; found in T-013 (spec drift rule). |
| 1.5 | 2026-10-31 | §7.2 `pending_interrupt` selects interrupts without a linked tool call (an approval for an unknown call would otherwise never be shown and the run would stay paused); found in T-014 (spec drift rule). |
| 1.6 | 2026-10-31 | §3.10 new internal field `resume`: `begin_run` captures the resume entries before clearing the interrupt bookkeeping, because the driver builds `RunAgentInput` after `begin_run`. When the last open interrupt is answered, the command leaves `run_status = idle` (INV-4) until the handler calls `begin_run` under the same lock. Found in T-015 (spec drift rule). |
| 1.7 | 2026-10-31 | §5 an oversized or non-JSON interrupt response is reported as an `IGNORED_EVENT` warning (no new diagnostic code); found in T-015 (spec drift rule). |
| 1.8 | 2026-10-31 | §3.10 `begin_run` is a no-op while `run_status == awaiting_input` (some interrupt is unanswered): starting a run would drop the open interrupts and leave calls `pending_approval` (INV-6). Mirrors REQ-015.1 at the command level; found by the T-018 property tests (spec drift rule). |
| 1.9 | 2026-10-31 | §7.1 a `TOOL_CALL_RESULT` for a `rejected` or `error` call records the result and the tool message but keeps the terminal status (API §4.6). PydanticAI sends one with the denial text after a rejected approval; found in T-034 (spec drift rule). |
| 1.10 | 2026-10-31 | §7.1 a `MESSAGES_SNAPSHOT` fills in the result of a kept tool call from its `tool` message. ag-ui-langgraph sends no `TOOL_CALL_RESULT` for a tool node's `ToolMessage`; the snapshot is the only place the result appears. Found in T-044 (spec drift rule). |
| 1.11 | 2026-10-31 | §7.1 a `MESSAGES_SNAPSHOT` fills in the arguments of a kept tool call that streamed none. With a model that sends a whole tool call in one chunk (Ollama through its OpenAI-compatible API), ag-ui-langgraph emits `TOOL_CALL_START` and `TOOL_CALL_END` with no `TOOL_CALL_ARGS`, so the approval dialog showed `{}`. Found in the T-052 fresh-environment walkthrough (spec drift rule). |
