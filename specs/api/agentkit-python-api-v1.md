# reflex-agentkit — Python API Specification

## Metadata

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo (`ecrespo`) |
| **Status** | `APPROVED` (2026-10-30) |
| **API version** | v1.4 (ships as package `0.1.0`) |
| **Date** | 2026-10-30 |
| **Related PRD** | [`specs/prd/agentkit-v0.1.md`](../prd/agentkit-v0.1.md) (APPROVED) |
| **Governed by** | [`specs/constitution.md`](../constitution.md) v1.1 |
| **Surface** | Python import API (`reflex_agentkit`) + AG-UI wire contract consumed by `HttpAGUIClient` |

> **How to read this document.** This is a *library* API, so the HTTP-oriented sections of
> the SDD template are adapted. "Endpoints" become public classes, functions and Reflex
> event handlers. "Error format" becomes the exception hierarchy plus the `error_code`
> state var. The one real wire protocol is AG-UI over SSE (§8), which this library consumes
> and does not define. Exact field types of the state models are finalized in the Data
> Model (`specs/data-model/agentkit-schema.md`). This document fixes names, signatures,
> semantics and invariants. Items marked **⟶ TD-verify** are API shapes whose
> feasibility the Technical Design must confirm against the pinned Reflex and adapter
> versions. If one fails, the fallback named next to it applies, with no other API change.

---

## 1. Overview

Consumers:

- **App developers (P1, P2):** use `AgentState`, the components and an adapter. They
  usually touch fewer than 10 names (§2).
- **Integrators (P3):** use the AG-UI client layer (`AgentClient`, `HttpAGUIClient`,
  `InProcessAGUIClient`) and the pure reducer (`reduce`) directly.
- **Adapter authors:** implement the `AGUIAgent` protocol (§7.1).

Layering (an import of a lower layer never pulls in a higher one):

```
reflex_agentkit.components   ← Reflex components (UI only, read public vars, call handlers)
reflex_agentkit.state        ← AgentState mixin (Reflex glue: streaming, batching, cancel)
reflex_agentkit.core         ← pure: models, reduce(), AgentClient, HTTP/in-process clients, tools
reflex_agentkit.adapters.*   ← optional extras: framework → AGUIAgent
```

`reflex_agentkit.core` does not import `reflex` (PRD REQ-005, Constitution Art. 5), so
integrators can use the reducer and the clients outside Reflex. Because Python runs the
parent package's `__init__` first, the top-level `reflex_agentkit/__init__.py` exposes the
Reflex-dependent names (`AgentState`, `agent_chat`) through **lazy re-exports** (PEP 562
module `__getattr__`): `import reflex_agentkit.core` never imports `reflex`. `reflex_agentkit.state`
and `reflex_agentkit.components` import `reflex`. `reflex_agentkit.adapters.*` import their
extras.

## 2. The quickstart (normative)

This is the contract that the rest of the API is designed backward from (PRD REQ-029). It
has 23 counted lines; the limit is 30.

```python
from typing import ClassVar

import reflex as rx
from pydantic_ai import Agent

from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

travel_agent = Agent(
    "anthropic:claude-sonnet-5-5",
    instructions="You are a helpful travel assistant.",
)


@travel_agent.tool_plain
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It is sunny and 22 °C in {city}."


@travel_agent.tool_plain(requires_approval=True)
def book_hotel(city: str, nights: int) -> str:
    """Book a hotel room. Requires human approval."""
    return f"Booked {nights} nights in {city}."


class ChatState(AgentState, rx.State):
    agent: ClassVar = PydanticAIAgent(travel_agent)


def index() -> rx.Component:
    return agent_chat(ChatState)


app = rx.App()
app.add_page(index)
```

The quickstart's default model is Claude. The docs show the one-line swap to a local
Ollama model (PydanticAI's Ollama provider). The CI smoke test replaces the model with
PydanticAI's `TestModel`, so it needs no network and no keys (REQ-030.2).

**Resolved (Q-1, TD DD-006):** Reflex turns an unannotated `agent = ...` in a subclass
into a state var and rejects it, so the `ClassVar` annotation is required. The
approval-required tool needs no `output_type=[str, DeferredToolRequests]`, because the
adapter injects it at run time (TD DD-011).

## 3. Public surface and stability

Everything listed in this section is **public API** under Constitution Art. 8 (SemVer;
one minor release of deprecation before any 0.x break). Names that start with `_`,
everything under `reflex_agentkit._internal`, and every backend-only state var (`_*`) are
private and may change in any release.

| Module | `__all__` |
|---|---|
| `reflex_agentkit` | `AgentState`, `agent_chat`, `client_tool`, `ClientTool`, `HttpAGUIClient`, `InProcessAGUIClient`, `AgentClient`, `AGUIAgent`, `AgentSource`, `RunStatus`, `ToolCallStatus`, `ErrorCode`, `AgentKitError`, `ConfigurationError`, `__version__` |
| `reflex_agentkit.core` | everything above that does not depend on Reflex (all but `AgentState`, `agent_chat` and `__version__`), plus `reduce`, `ConversationState`, `Diagnostic`, `ChatMessage`, `ToolCall`, `PendingInterrupt`, `CustomEventRecord`, `RunInputBuilder`, `AgentHTTPError`, `AgentStreamError`, `AdapterNotInstalledError` |
| `reflex_agentkit.components` | `agent_chat`, `message_list`, `composer`, `tool_call_card`, `approval_dialog`, `run_status_bar`, `shared_state_panel`, `ToolRenderer`, `InterruptRenderer` |
| `reflex_agentkit.adapters.pydantic_ai` | `PydanticAIAgent` |
| `reflex_agentkit.adapters.langgraph` | `LangGraphAGUIAgent`, `request_tool_approval`, `ApprovalDecision` |

`reflex_agentkit.__version__` is a `str` literal in `src/reflex_agentkit/__init__.py`. It is
the single source of the package version and is read by hatchling at build time.

## 4. `AgentState` — the Reflex state mixin

```python
class AgentState(rx.State, mixin=True):
    ...
```

Used as `class MyState(AgentState, rx.State): ...`. The mixin must come first in the
bases, as Reflex requires for mixins.

### 4.1 Configuration (class-level, never sent to the browser)

All of these are `ClassVar`s. They describe the app, not the session, so none of them is
ever a state var (Constitution Art. 3, PRD REQ-025). **A subclass that overrides one must
annotate it as `ClassVar`** (`agent: ClassVar = ...`, `flush_interval_ms: ClassVar = 30`).
Without the annotation, Reflex treats the attribute as a state var (TD DD-006).

| Name | Type | Default | Meaning | REQ |
|---|---|---|---|---|
| `agent` | `ClassVar[AgentSource \| None]` | `None` | The agent to talk to. It is either an `AgentClient`, or an `AGUIAgent` that is wrapped automatically in `InProcessAGUIClient`. Required unless `create_client()` is overridden. | 021 |
| `client_tools` | `ClassVar[Sequence[ClientTool]]` | `()` | Tools advertised to the agent and executed in the app (§6). | 018 |
| `shared_state_model` | `ClassVar[type[pydantic.BaseModel] \| None]` | `None` | Optional validation model for `shared_state` (PRD D-04). | 016.5–6 |
| `flush_interval_ms` | `ClassVar[int]` | `50` | Maximum push rate during streaming. `0` pushes every event. Must be ≥ 0. | 006 |
| `max_message_length` | `ClassVar[int]` | `32_000` | Character limit for `send_message`. | 001.5 |
| `client_tool_timeout_s` | `ClassVar[float]` | `30.0` | Default per-handler timeout. A `ClientTool` can override it. | 018.5 |
| `custom_events_limit` | `ClassVar[int]` | `100` | Ring-buffer size of `custom_events`. | 010.5 |
| `max_client_tool_rounds` | `ClassVar[int]` | `8` | Maximum consecutive client-tool → follow-up-run rounds in one turn. Must be ≥ 1. | 018 (TD DD-009) |

`AgentSource = AgentClient | AGUIAgent`.

IF configuration is invalid (no `agent` and no `create_client` override, a negative
interval, a duplicate client-tool name, or `shared_state_model` that is not a `BaseModel`
subclass), THEN `ConfigurationError` is raised **when the subclass is defined**, not on
first use. The message names the attribute.

### 4.2 Public state vars (read-only for app code; sent to the browser)

App code and components **read** these vars. Only the library's handlers write them.

| Var | Type | Initial | Meaning | REQ |
|---|---|---|---|---|
| `messages` | `list[ChatMessage]` | `[]` | Conversation in order (§5.1) | 001, 008, 010.4 |
| `tool_calls` | `list[ToolCall]` | `[]` | All tool calls of the thread, in start order (§5.2) | 009, 013 |
| `pending_interrupt` | `PendingInterrupt \| None` | `None` | The current *generic* interrupt (not tool approvals) | 014 |
| `shared_state` | `dict[str, Any]` | `{}` | Mirrored agent state (JSON) | 016 |
| `shared_state_stale` | `bool` | `False` | A delta failed to apply. True until the next snapshot. | 016.3–4 |
| `run_status` | `RunStatus` (str literal) | `"idle"` | §4.5 | 004, 007, 015 |
| `current_step` | `str` | `""` | Name of the active AG-UI step | 010.3 |
| `thread_id` | `str` | `""` | Created lazily on the first run (PRD D-02) | 002 |
| `run_id` | `str` | `""` | The active run, or the last one | 001.2, 010.1 |
| `error` | `str` | `""` | Human-readable message of the last error; `""` when there is none | 001.5, 004.3 |
| `error_code` | `ErrorCode \| None` | `None` | Machine-readable code (§9.2) | — |
| `custom_events` | `list[CustomEventRecord]` | `[]` | The last N CUSTOM events | 010.5 |

**Computed vars** (public, read-only):

| Var | Type | Definition |
|---|---|---|
| `is_running` | `bool` | `run_status == "running"` |
| `awaiting_input` | `bool` | `run_status == "awaiting_input"` |
| `pending_approvals` | `list[ToolCall]` | calls with `status == "pending_approval"`, in start order |
| `can_send` | `bool` | `run_status in {"idle", "cancelled", "error"}` |

### 4.3 Event handlers (public)

Every handler is a Reflex event handler, so it can be bound to component triggers
(`on_click=ChatState.cancel_run`) or returned from other handlers. Handlers that start a
run return immediately. Streaming happens in a background task.

```python
def send_message(self, text: str) -> ...
def approve_tool(self, call_id: str, edited_args: dict[str, Any] | str | None = None) -> ...
def reject_tool(self, call_id: str, reason: str | None = None) -> ...
def respond_to_interrupt(self, payload: Any) -> ...
def cancel_run(self) -> ...
def new_thread(self) -> ...
def set_shared_state(self, value: dict[str, Any]) -> ...          # SHOULD (REQ-017)
def patch_shared_state(self, ops: list[dict[str, Any]]) -> ...     # SHOULD (REQ-017)
def retry_run(self) -> ...                                         # COULD  (REQ-028)
```

| Handler | Allowed when | Effect | No-op / error when | REQ |
|---|---|---|---|---|
| `send_message(text)` | `can_send` | Appends a `user` message and starts a run. `text` is stripped of surrounding whitespace before it is checked and stored. | Empty text: no-op. Too long: `error_code=MESSAGE_TOO_LONG`. Wrong status: no-op. | 001 |
| `approve_tool(call_id, edited_args=None)` | the call is `pending_approval` | Records `{"approved": true}` or `{"approved": true, "editedArgs": …}`. Starts the resume run when every interrupt has an answer. A `str` `edited_args` is parsed as JSON (so a JSON editor can bind to it directly). | Unknown call or wrong status: no-op. `edited_args` is not a JSON object: `error_code=INVALID_EDITED_ARGS` and the call stays pending. | 013.2–3, 6–7 |
| `reject_tool(call_id, reason=None)` | the call is `pending_approval` | Records `{"approved": false[, "reason": reason]}` and sets status `rejected`. | as above | 013.4, 6 |
| `respond_to_interrupt(payload)` | `pending_interrupt` is set | Records `ResumeEntry(status="resolved", payload)` and moves to the next generic interrupt, or resumes. A `str` payload is parsed as JSON when it is valid JSON and is otherwise sent as a string. | `pending_interrupt is None`: no-op. | 014.2–4 |
| `cancel_run()` | `running` or `awaiting_input` | §4.5 transitions. While running, it stops the stream and closes the upstream. While awaiting input, it rejects the open approvals and remembers the interrupt IDs so the next run cancels them. | Other states: no-op. | 007, 015.2–3 |
| `new_thread()` | any | Cancels a running run if there is one, then resets every public var to its initial value with a new `thread_id`. | — | 002.3–4 |
| `set_shared_state(value)` | `run_status != running` | Replaces `shared_state` and validates it against `shared_state_model` if one is set. | While running: `error_code=SHARED_STATE_LOCKED`. Invalid: `error_code=SHARED_STATE_INVALID`. | 017 |
| `patch_shared_state(ops)` | `run_status != running` | Applies RFC 6902 `ops` atomically. | as above, plus `SHARED_STATE_PATCH_FAILED` | 017 |
| `retry_run()` | `error` or `cancelled` | Truncates after the last `user` message and starts a run. **Backend tools may run again:** tools with external side effects should be idempotent or use `requires_approval=True`; approval-required tools ask again. | otherwise no-op | 028 |

`drive_run()` is the background handler that streams a run. Reflex does not allow private
event handlers, so it is public, but it takes no arguments and does nothing unless a
handler above has just scheduled a run (TD §6.1). App code never calls it.

**Concurrency invariant:** at most one run is in flight per state instance (per client
session). Every handler is safe to call from the browser at any time. Calls that are not
allowed in the current state are no-ops, so double-clicks and races between `cancel_run`
and the stream's end cannot corrupt state.

### 4.4 Overridable hooks (extension points)

Each hook has a default implementation. A subclass overrides it with a normal method
(not an event handler).

| Hook | Signature | Default | Called | Use for |
|---|---|---|---|---|
| `create_client` | `def create_client(self) -> AgentClient` | Wraps `type(self).agent` | Once per run, server-side | Per-session clients, e.g. auth headers from the user's session. The returned object is held only in backend memory. |
| `prepare_run_input` | `def prepare_run_input(self, run_input: RunAgentInput) -> RunAgentInput` | identity | Before each run | Adding `context`, `forwarded_props` or extra tools |
| `on_custom_event` | `async def on_custom_event(self, name: str, value: Any) -> None` | no-op | After the reducer applies a CUSTOM event, under the state lock | App reactions to CUSTOM events. Exceptions are logged and swallowed (REQ-020.2). |
| `on_run_end` | `async def on_run_end(self, status: RunStatus) -> None` | no-op | Once per run, after the final flush | Analytics in the host app, notifications. *(COULD)* |

**Typed shared state** (REQ-016.6): `def typed_shared_state(self) -> pydantic.BaseModel`
returns `shared_state_model.model_validate(self.shared_state)` for server-side code. It
raises `ConfigurationError` when no `shared_state_model` is set, and
`pydantic.ValidationError` if the stored value does not validate (which REQ-016.5 prevents
for every write and every agent update).

Hooks run on the event loop and must not block (Constitution Art. 4). Inside a hook,
read class-level configuration through `self.__class__`, not `type(self)`: during a run
Reflex binds the hooks to a `StateProxy`, whose `type()` is the proxy class. Hooks that run
under the lock must return quickly; slow work belongs in a separate background event.

### 4.5 Run status state machine

`RunStatus = Literal["idle", "running", "awaiting_input", "cancelled", "error"]`

```
                send_message / retry_run / (all interrupts answered → auto resume)
   ┌──────┐ ─────────────────────────────────────────────────────────▶ ┌─────────┐
   │ idle │                                                            │ running │
   └──────┘ ◀──────────────── RUN_FINISHED (no interrupt) ─────────────└────┬────┘
      ▲  ▲                                                                  │
      │  │                       RUN_FINISHED(outcome=interrupt)            │
      │  │                ┌────────────────┐ ◀─────────────────────────────┤
      │  │                │ awaiting_input │ ── all answered ──▶ running    │
      │  │                └───────┬────────┘                                │
      │  │                        │ cancel_run                              │ cancel_run
      │  │                        ▼                                         ▼
      │  │                  ┌───────────┐ ◀─────────────────────────────────┘
      │  └── new_thread ─── │ cancelled │ ── send_message / retry_run ──▶ running
      │                     └───────────┘
      │                     ┌───────────┐
      └──── new_thread ──── │   error   │ ── send_message / retry_run ──▶ running
                            └───────────┘ ◀── RUN_ERROR · HTTP error · stream EOF · timeout
                                              (from running)
```

`RUN_FINISHED(outcome=cancelled)` from an agent leads from `running` to `cancelled` (§8.3).
`RUN_FINISHED` with no interrupt leads to `idle` only when no client-side tool call awaits
execution (PRD REQ-004.1). `new_thread()` from any state leads to `idle`. Client-side tool execution (§6) happens
while the status stays `running`: the follow-up run starts without passing through
`idle`.

### 4.6 Tool call status state machine

`ToolCallStatus = Literal["streaming", "pending_approval", "running", "done", "rejected", "error"]`

```
TOOL_CALL_START
      │
      ▼
 ┌───────────┐  TOOL_CALL_END (backend tool)        ┌─────────┐  TOOL_CALL_RESULT /     ┌──────┐
 │ streaming │ ───────────────────────────────────▶ │ running │ ──client handler ok───▶ │ done │
 └─────┬─────┘                                       └────┬────┘                         └──────┘
       │ RUN_FINISHED interrupt(reason=tool_call)          │ handler raises / timeout /
       │ or client tool with requires_approval             │ cancel / invalid args
       ▼                                                    ▼
 ┌──────────────────┐ approve_tool ──▶ running         ┌───────┐
 │ pending_approval │                                  │ error │
 └────────┬─────────┘                                  └───────┘
          │ reject_tool / cancel_run while awaiting_input
          ▼
     ┌──────────┐
     │ rejected │
     └──────────┘
```

A backend tool call can be in `running` when `RUN_FINISHED` with a matching interrupt
arrives; that also moves it to `pending_approval`. Invalid JSON args at `TOOL_CALL_END`
lead straight to `error` (REQ-009.7). `done`, `rejected` and `error` are terminal.
`approve_tool` moves a call to `running` immediately, even while other interrupts of the
same pause are unanswered and the resume run has not started yet (accepted, Analyze A-17).

## 5. Public value types (`reflex_agentkit.core`)

Frozen, JSON-serializable value objects. Exact field types and the Reflex var
representation are decided in the Data Model. Field names here are normative.

### 5.1 `ChatMessage`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | AG-UI `messageId`. Library-generated UUID4 for `user` messages. |
| `role` | `Literal["user", "assistant", "tool"]` | **AG-UI role names.** The PRD's "human message" is `role == "user"`. |
| `content` | `str` | Accumulates during streaming |
| `streaming` | `bool` | True between START and END |
| `tool_call_ids` | `list[str]` | For `assistant` messages: the calls it issued |
| `tool_call_id` | `str \| None` | For `tool` messages: the call this result belongs to |
| `reasoning` | `str` | Accumulated `REASONING_*` text for this assistant turn (`""` if none). Stored only; v0.1 components do not render it (EP-4). |
| `is_error` | `bool` | For `tool` messages: the tool failed or was rejected (AG-UI `ToolMessage.error`). `False` otherwise. |

### 5.2 `ToolCall`

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | AG-UI `toolCallId` |
| `name` | `str` | AG-UI `toolCallName` |
| `args_text` | `str` | Raw accumulated `TOOL_CALL_ARGS` deltas |
| `args` | `dict[str, Any] \| None` | Parsed args whenever `args_text` is valid JSON. Replaced by the edited args on an approval with edits. |
| `status` | `ToolCallStatus` | §4.6 |
| `result` | `str \| None` | Tool result content, or an error/rejection text |
| `parent_message_id` | `str \| None` | Assistant message that issued it |
| `interrupt_id` | `str \| None` | Set while it is (or was) `pending_approval` |
| `is_client_tool` | `bool` | Whether it is handled by a `ClientTool` (§6) |

### 5.3 `PendingInterrupt`

Mirrors AG-UI `Interrupt` for reasons other than `tool_call`.

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | AG-UI `Interrupt.id`, echoed in `ResumeEntry.interrupt_id` |
| `reason` | `str` | Free-form reason from the agent (e.g. `"human_input"`) |
| `message` | `str` | Prompt to show the user (`""` if absent) |
| `payload` | `Any` | Agent-supplied value (for LangGraph, the `interrupt(value)` argument) |
| `response_schema` | `dict[str, Any] \| None` | JSON Schema for the answer, when the agent provides one |
| `queue_position` | `int` | 1-based position among the generic interrupts of this pause (REQ-014.3) |
| `queue_size` | `int` | Number of generic interrupts in this pause |

### 5.4 `CustomEventRecord`
`name: str`, `value: Any`, `run_id: str`.

### 5.5 Enums
`RunStatus` (§4.5), `ToolCallStatus` (§4.6), `ErrorCode` (§9.2). All are `StrEnum`
(Python 3.11+), so `run_status == "running"` and `== RunStatus.RUNNING` both hold.

## 6. Client-side tools

```python
from reflex_agentkit import client_tool

@client_tool(requires_approval=False, timeout_s=None)
async def show_chart(title: str, values: list[float]) -> str:
    """Render a bar chart in the chat."""
    return "chart shown"

class ChatState(AgentState, rx.State):
    agent = ...
    client_tools = [show_chart]
```

```python
def client_tool(
    func: Callable[..., Awaitable[Any]] | None = None,
    *,
    name: str | None = None,              # default: func.__name__
    description: str | None = None,       # default: first docstring paragraph
    requires_approval: bool = False,
    timeout_s: float | None = None,       # default: AgentState.client_tool_timeout_s
) -> ClientTool | Callable[[Callable[..., Awaitable[Any]]], ClientTool]
```

- The JSON Schema `parameters` come from the type hints (Pydantic `TypeAdapter`). IF a
  parameter has no type hint, or a hint that cannot be represented as JSON Schema, THEN
  `ConfigurationError` is raised at decoration time.
- A handler may be `async def` or plain `def`. A sync handler runs in a worker thread
  (Constitution Art. 4, REQ-024.2).
- The return value is the tool result. `str` is sent as-is; anything else is JSON-encoded.
  `None` is sent as `""`.
- **Render-only tools** (tool-based generative UI): a handler that does nothing but
  return a confirmation is the idiom. The UI comes from a tool renderer (§10.2) keyed
  by the same name.
- `ClientTool` is a frozen dataclass:
  `name`, `description`, `parameters: dict[str, Any]`, `handler`, `requires_approval`,
  `timeout_s`. The method `to_agui_tool() -> ag_ui.core.Tool` produces the advertised
  definition.

Handlers run server-side with the parsed (or edited) args. They receive only those args,
never the state. A handler that needs session data is a closure or a bound method of a
non-state object. **⟶ TD-verify (Q-2):** whether to also inject an optional
`ctx: ToolContext` parameter (thread_id, run_id, a read-only shared_state snapshot).
*Fallback:* none in v0.1.

## 7. Agent client layer (`reflex_agentkit.core`)

### 7.1 `AGUIAgent` protocol (what adapters implement)

```python
@runtime_checkable
class AGUIAgent(Protocol):
    def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]: ...
```

Contract for implementers:
1. Yield `ag_ui.core` event objects (not encoded strings) in protocol order, starting
   with `RUN_STARTED` and ending with exactly one `RUN_FINISHED` or `RUN_ERROR`.
2. Cancellation is delivered by cancelling the consuming task or calling `aclose()` on
   the iterator. Implementations must release upstream resources (model streams, graph
   runs) in `finally` blocks and must not suppress `CancelledError`.
3. They must not block the event loop. Synchronous frameworks offload their work.
4. They must emit human-in-the-loop requests as AG-UI standard interrupts:
   `RUN_FINISHED.outcome = {"type": "interrupt", "interrupts": [...]}`. Tool approvals
   use `reason="tool_call"` and set `tool_call_id`. On resume, they must honor
   `RunAgentInput.resume[]` with the approval payload contract in §7.4.

### 7.2 `AgentClient` protocol (what `AgentState` consumes)

```python
@runtime_checkable
class AgentClient(Protocol):
    def stream(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]: ...
    async def aclose(self) -> None: ...
```

- `stream` yields validated `ag_ui.core` events.
- Cancelling the consumer, or calling `aclose()` on the iterator, must close the upstream
  within 1 s (REQ-007.1–3).
- Transport failures are raised as `AgentHTTPError` or `AgentStreamError` (§9.1). A
  client never yields a synthetic `RUN_ERROR`; `AgentState` maps exceptions to status and
  error codes.
- Events that fail AG-UI validation are skipped and logged by the client, not raised
  (REQ-012.3).
- `aclose()` releases pooled resources (e.g., an `httpx.AsyncClient`) and is idempotent.

### 7.3 Implementations

```python
class HttpAGUIClient:
    def __init__(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | Callable[[], Mapping[str, str]] | None = None,
        timeout: httpx.Timeout | float = httpx.Timeout(10.0, read=60.0),
        http_client: httpx.AsyncClient | None = None,   # caller-owned; not closed by aclose()
    ) -> None: ...

class InProcessAGUIClient:
    def __init__(self, agent: AGUIAgent) -> None: ...
```

- `HttpAGUIClient` implements the wire contract in §8. Callable `headers` are evaluated
  per run, which supports rotating tokens. Headers are never logged, never put in state,
  and never included in exception messages (REQ-021.3, REQ-021.6).
- `InProcessAGUIClient` calls `agent.run()` in the current event loop. Cancellation
  cancels the iteration task; the agent observes `CancelledError` (REQ-007.3).
- Both are safe to share across sessions: they hold no per-run state.

### 7.4 Resume payload contract (both adapters and any compliant agent)

| Interrupt kind | `ResumeEntry.status` | `ResumeEntry.payload` |
|---|---|---|
| Tool approval, approved | `"resolved"` | `{"approved": true}` |
| Tool approval, approved with edits | `"resolved"` | `{"approved": true, "editedArgs": {…}}` |
| Tool approval, rejected | `"resolved"` | `{"approved": false}` or `{"approved": false, "reason": "…"}` |
| Generic interrupt answered | `"resolved"` | the app-supplied payload, as-is |
| Any interrupt abandoned by `cancel_run` | `"cancelled"` | omitted |

This is PydanticAI v2's native contract. The LangGraph adapter implements the same one
(§7.6).

### 7.5 PydanticAI adapter (`pip install reflex-agentkit[pydantic-ai]`)

```python
class PydanticAIAgent:   # implements AGUIAgent
    def __init__(
        self,
        agent: pydantic_ai.Agent[Any, Any],
        *,
        deps: Any = None,
        deps_factory: Callable[[RunAgentInput], Any | Awaitable[Any]] | None = None,
        **run_kwargs: Any,   # forwarded to AGUIAdapter.run_stream (e.g. model_settings, usage_limits)
    ) -> None: ...
```

- Drives `pydantic_ai.ui.ag_ui.AGUIAdapter(agent=..., run_input=...).run_stream()` in
  process (REQ-022.1).
- `deps` and `deps_factory` are mutually exclusive. Setting both raises
  `ConfigurationError`. The factory receives the run input (thread_id is available) and
  is the place to build per-session deps.
- When the agent's `output_type` does not already include `DeferredToolRequests`, the
  adapter passes `output_type=[agent.output_type, DeferredToolRequests]` to `run_stream`.
  Approval-required tools therefore pause cleanly with no user configuration (resolved
  Q-3, TD DD-011). REQ-022.4's configuration error is satisfied by construction: the
  "cannot express deferred requests" situation cannot arise.
- `client_tools` from `AgentState` arrive as `RunAgentInput.tools`. PydanticAI exposes
  them to the model as frontend tools, and their calls end the run with a pending
  frontend tool call (§6 flow).

### 7.6 LangGraph adapter (`pip install reflex-agentkit[langgraph]`)

```python
class LangGraphAGUIAgent:   # implements AGUIAgent
    def __init__(
        self,
        graph: CompiledStateGraph,
        *,
        name: str = "agent",
        config: RunnableConfig | None = None,
        legacy_interrupts: bool = False,   # SHOULD (REQ-034.5): map `on_interrupt` CUSTOM events
    ) -> None: ...

@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    args: dict[str, Any]          # original or edited args (edited take precedence)
    reason: str | None = None

def request_tool_approval(
    tool_call_id: str, tool_name: str, args: dict[str, Any], *, message: str | None = None
) -> ApprovalDecision: ...
```

- Subclasses `ag_ui_langgraph.LangGraphAgent` with `emit_interrupt_outcome=True`,
  `enable_legacy_on_interrupt_event=False` and `emit_raw_events=False` (REQ-034.1, TD
  DD-012). Multiple resume entries are delivered as LangGraph's native
  `Command(resume={interrupt_id: payload})`.
- IF `graph.checkpointer` is `None`, THEN `ConfigurationError` is raised in `__init__`
  (REQ-034.4).
- `interrupt(value)` in the graph appears as `pending_interrupt` with
  `payload = value`. `respond_to_interrupt(p)` resumes the graph with
  `Command(resume=p)` (REQ-034.2).
- `request_tool_approval(...)` is called *inside a graph node or tool*. It calls
  LangGraph `interrupt({"reason": "tool_call", "toolCallId": ..., "toolName": ..., "args": ..., "message": ..., "responseSchema": ...})`.
  ag-ui-langgraph maps those keys natively onto the AG-UI `Interrupt` (resolved Q-4, TD
  DD-012), so the UI shows a `pending_approval` tool card, not a generic interrupt
  (REQ-034.3). It returns an `ApprovalDecision` built from the §7.4 payload. A
  cancelled approval returns `ApprovalDecision(approved=False, args=<original>, reason="cancelled")`.
- A generic `interrupt()` that is cancelled resumes with the upstream sentinel
  `{"__agui_cancelled__": True, "interrupt_id": ...}`. Graph authors check for it.

### 7.7 Missing extras

Importing `reflex_agentkit.adapters.pydantic_ai` without `pydantic-ai` installed raises
`AdapterNotInstalledError` (a subclass of `ImportError`) with the message
`"reflex_agentkit.adapters.pydantic_ai requires the 'pydantic-ai' extra: pip install 'reflex-agentkit[pydantic-ai]'"`.
The LangGraph adapter does the same with `'langgraph'` (REQ-031.3).

## 8. AG-UI wire contract (consumed by `HttpAGUIClient`)

The library is an AG-UI **consumer**. Any server that meets this section works.

### 8.1 Request

```http
POST {url}
Content-Type: application/json
Accept: text/event-stream
{headers from HttpAGUIClient}

{ RunAgentInput, JSON-encoded with camelCase keys (ag_ui.core serialization) }
```

`RunAgentInput` composition (built by `RunInputBuilder`, then `prepare_run_input`):

| Field | Value |
|---|---|
| `threadId` | `thread_id` |
| `runId` | new UUID4 per run |
| `protocolVersion` | `"1.0"` |
| `messages` | full history converted to AG-UI messages. Assistant messages carry `toolCalls`. Client-tool results are `tool` messages. `REASONING_ENCRYPTED_VALUE`s are re-attached as AG-UI requires (REQ-011.2). |
| `state` | `shared_state` (REQ-016.7) |
| `tools` | `[t.to_agui_tool() for t in client_tools]` |
| `context` | `[]` (extend through `prepare_run_input`) |
| `forwardedProps` | `{}` (extend through `prepare_run_input`) |
| `resume` | present only when the run answers interrupts (§7.4) |

### 8.2 Response

- Status `2xx` with `Content-Type: text/event-stream`. Each SSE event's `data:` field
  holds one JSON-encoded AG-UI event. The `event:`/`id:` fields and comment lines are
  ignored. Multi-line `data:` fields are joined per the SSE specification.
- Non-`2xx`: `AgentHTTPError(status_code)`. The body (truncated to 1 KiB) is logged at
  DEBUG; no headers are logged (REQ-021.3).
- `2xx` with a different content type: `AgentStreamError("unexpected content type")`.
- No bytes for `timeout.read` seconds: `AgentStreamError("read timeout")` (REQ-021.4).
- EOF before `RUN_FINISHED`/`RUN_ERROR`: `AgentStreamError("stream ended unexpectedly")`
  (REQ-004.4).

### 8.3 Event handling contract

| Event family | v0.1 behavior | REQ |
|---|---|---|
| `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR` | Lifecycle. `RUN_FINISHED.outcome`: absent or `success` → `idle`; `interrupt` → `awaiting_input`; `cancelled` → `cancelled`. | 004, 010.1–2 |
| `STEP_STARTED`, `STEP_FINISHED` | `current_step` | 010.3 |
| `TEXT_MESSAGE_START/CONTENT/END/CHUNK` | `messages` | 008 |
| `TOOL_CALL_START/ARGS/END/CHUNK/RESULT` | `tool_calls`, `tool` messages | 009 |
| `STATE_SNAPSHOT`, `STATE_DELTA` | `shared_state` | 016 |
| `MESSAGES_SNAPSHOT` | Replaces `messages` | 010.4 |
| `CUSTOM` | `custom_events` and the `on_custom_event` hook | 010.5, 020 |
| `REASONING_*` | `ChatMessage.reasoning`. The encrypted value stays backend-only. | 011 |
| `ACTIVITY_*`, `SUBAGENT_*`, `RAW` | Accepted, no visible change | 012.1 |
| `THINKING_*` (removed from the ag-ui-protocol 1.0 Python enum), unknown types | Skipped, DEBUG diagnostic | 012.2 |

## 9. Errors

### 9.1 Exception hierarchy (raised to *developers*, never to the browser)

```
AgentKitError(Exception)
├── ConfigurationError(AgentKitError, ValueError)     # invalid class config, tool schema, adapter setup
├── AdapterNotInstalledError(AgentKitError, ImportError)
├── AgentHTTPError(AgentKitError)                     # .status_code: int
└── AgentStreamError(AgentKitError)                   # .reason: str  (timeout, eof, content_type, connect, agent_raised)
```

`AgentState` catches `AgentHTTPError`, `AgentStreamError` and handler exceptions during a
run and maps them to `run_status`, `error` and `error_code`. They never escape a
background task. `ConfigurationError` is raised at class-definition or construction time,
so it fails at startup, not mid-session.

### 9.2 `ErrorCode` (surfaced in the `error_code` state var)

| Code | Set when | `run_status` after | REQ |
|---|---|---|---|
| `MESSAGE_TOO_LONG` | `send_message` exceeds `max_message_length` | unchanged | 001.5 |
| `AGENT_RUN_ERROR` | `RUN_ERROR` received. `error` = event message; the AG-UI `code` is logged. | `error` | 004.3 |
| `AGENT_HTTP_ERROR` | non-2xx from the endpoint. `error` contains the status code only. | `error` | 021.3 |
| `AGENT_STREAM_ERROR` | timeout, EOF, connection drop, unexpected content type | `error` | 004.4, 021.4 |
| `AGENT_EXCEPTION` | an in-process agent raised an exception (not `CancelledError`; surfaced as `AgentStreamError(reason="agent_raised")`), or `create_client()` failed. HTTP connect failures are `AGENT_STREAM_ERROR`. | `error` | 021 |
| `INVALID_EDITED_ARGS` | `approve_tool` with args that are not a JSON object | unchanged (`awaiting_input`) | 013.7 |
| `SHARED_STATE_LOCKED` | an app write while running | unchanged | 017.2 |
| `SHARED_STATE_INVALID` | a snapshot, delta or app write fails `shared_state_model` validation | unchanged (non-fatal) | 016.5 |
| `SHARED_STATE_PATCH_FAILED` | an RFC 6902 delta (agent or app) fails to apply | unchanged (non-fatal) | 016.3 |
| `CLIENT_TOOL_LOOP_LIMIT` | more than `max_client_tool_rounds` consecutive client-tool rounds | `error` | 018 (TD DD-009) |

Client-tool failures are **not** run errors. The tool call goes to `error` and the
conversation continues (REQ-018.4), so no `error_code` is set. `error` and `error_code`
are cleared when the next run starts (REQ-001.3).

## 10. Components (`reflex_agentkit.components`)

Every component takes the state **class** as its first positional argument, accepts
standard Reflex `**props` (style, class_name, etc.) on its root element, and uses only
Reflex built-in components (Constitution Art. 2, REQ-023.8). Signatures:

```python
def agent_chat(
    state: type[AgentState],
    *,
    tool_renderers: Mapping[str, ToolRenderer] | None = None,
    interrupt_renderers: Mapping[str, InterruptRenderer] | None = None,
    show_shared_state: bool = False,
    placeholder: str = "Send a message…",
    **props: Any,
) -> rx.Component: ...

def message_list(state, *, tool_renderers=None, **props) -> rx.Component: ...
def composer(state, *, placeholder: str = "Send a message…", **props) -> rx.Component: ...
def tool_call_card(state, tool_call: Var[ToolCall], *, body: ToolRenderer | None = None, **props) -> rx.Component: ...
def approval_dialog(state, *, interrupt_renderers=None, **props) -> rx.Component: ...
def run_status_bar(state, **props) -> rx.Component: ...
def shared_state_panel(state, **props) -> rx.Component: ...
```

### 10.1 Behavior

The behavior of each component is defined by PRD REQ-023.1–9. In particular:
- `composer` is disabled unless `state.can_send`.
- `approval_dialog` is open while `pending_approvals` is non-empty or `pending_interrupt`
  is set. It shows one item at a time, approvals first and then generic interrupts.

### 10.2 Renderer contracts

```python
ToolRenderer = Callable[[Var[ToolCall]], rx.Component]
InterruptRenderer = Callable[[Var[PendingInterrupt], type[AgentState]], rx.Component]
```

- `tool_renderers` are keyed by tool name. A renderer replaces the *body* of
  `tool_call_card`; the header with name and status badge is kept. Renderers are
  resolved at compile time through `rx.match` on `tool_call.name`. Unregistered names use
  the default body (REQ-019). **⟶ TD-verify (Q-5):** that `rx.match` inside `rx.foreach`
  over typed vars compiles for N renderers. *Fallback:* `rx.cond` chains generated per
  name.
- `interrupt_renderers` are keyed by `PendingInterrupt.reason`. The renderer must call
  `state.respond_to_interrupt(payload)` itself. With no renderer for the reason, the
  default is a message plus a JSON editor validated against `response_schema` when one
  is present (REQ-023.5).

## 11. Pure reducer (`reflex_agentkit.core`)

```python
def reduce(state: ConversationState, event: BaseEvent) -> ConversationState: ...
```

- `ConversationState` is an immutable value that holds everything the reducer owns:
  messages, tool calls, pending interrupts, shared state and staleness, run status,
  current step, active run id, the set of registered client-tool names, and
  `diagnostics: tuple[Diagnostic, ...]`. Its exact fields are defined in the Data Model.
  `AgentState` keeps one in a backend-only var and projects it onto the public vars at
  each flush.
- `Diagnostic` = `(level: Literal["debug", "warning"], code: str, message: str, event_type: str | None)`.
  Diagnostics carry the out-of-order and unknown-event warnings (REQ-008.5, 009.6,
  012.2–3, 016.3). The state layer logs them and then clears them.
- **Guarantees:** total (never raises for any validated `BaseEvent`), pure and
  deterministic (REQ-005.1–2). Command-side transitions that are not events
  (`approve_tool`, `cancel_run`, …) are pure functions in the same module (`apply_approval`,
  `apply_rejection`, `apply_cancel`, `apply_interrupt_response`, `begin_run`). They are
  public for integrators and covered by the same fixture tests. Their names are listed
  in the Data Model.

## 12. Versioning and deprecation

- **Package:** SemVer starting at `0.1.0`. This document is API **v1**, the 0.x baseline.
- **Breaking change** = renaming or removing anything in §3, or changing a signature,
  public var name or type, handler precondition, status literal, error code, or the
  resume payload (§7.4). Each one needs a `DeprecationWarning` for at least one minor
  release, a CHANGELOG entry and an approved delta spec in `changes/` (Constitution
  Art. 8–9).
- **Additive changes** (new optional kwargs, new hooks, new error codes, handling of new
  AG-UI event types) are minor releases.
- **AG-UI compatibility:** the supported `ag-ui-protocol` range is pinned in the TD.
  Accepting a new upstream event family without rendering it is not a breaking change
  (REQ-012).

## 13. Traceability (PRD → API)

| REQ | API section |
|---|---|
| 001 | §4.3 `send_message`, §4.1 `max_message_length`, §9.2 |
| 002 | §4.2 `thread_id`, §4.3 `new_thread`, §8.1 |
| 003 | §4.3 concurrency invariant; per-session state (Reflex) |
| 004 | §4.5, §8.2, §9.2 |
| 005 | §11 |
| 006 | §4.1 `flush_interval_ms` |
| 007 | §4.3 `cancel_run`, §4.5, §7.2–7.3 |
| 008, 009, 010, 011, 012 | §5.1–5.2, §8.3, §11 |
| 013 | §4.3 `approve_tool`/`reject_tool`, §4.6, §7.4 |
| 014 | §4.3 `respond_to_interrupt`, §5.3, §10.2 |
| 015 | §4.3 `cancel_run`, §4.5, §7.4 (cancelled entries) |
| 016, 017 | §4.1 `shared_state_model`, §4.2, §4.3, §9.2 |
| 018 | §6 |
| 019 | §10.2 `tool_renderers` |
| 020 | §4.4 `on_custom_event` |
| 021 | §7.2–7.3, §8 |
| 022 | §7.5 |
| 023 | §10 |
| 024 | §6 (sync handlers), §7.1.3, §4.4 |
| 025 | §4.1 (ClassVars), §4.4 `create_client`, §7.3 headers |
| 026 | Behavioral; mechanism → TD (D-02). No API surface. |
| 027 | `logging.getLogger("reflex_agentkit")`; no API surface |
| 028 | §4.3 `retry_run` |
| 029 | §2 |
| 030–033 | Not API surface (examples, packaging, CI, docs) |
| 034 | §7.6 |

## 14. Open items for the Technical Design (all resolved, TD v1.0)

| ID | Question | Resolution |
|---|---|---|
| Q-1 | An inherited `ClassVar` lets subclasses assign `agent = ...` without Reflex creating a var | **No.** The explicit `agent: ClassVar = ...` fallback is adopted (DD-006). |
| Q-2 | Optional `ToolContext` injection into client-tool handlers | **Not in v0.1** (candidate for v0.2) |
| Q-3 | PydanticAI adapter injects `DeferredToolRequests` at run time | **Yes**, verified (DD-011) |
| Q-4 | Raw LangGraph interrupt value → AG-UI `Interrupt` mapping | **Native key mapping**, verified; no rewriting (DD-012) |
| Q-5 | `rx.match` on tool name inside `rx.foreach` | **Works**, verified (DD-013) |

---

## Constitution Check

| Article | Compliance |
|---|---|
| Art. 1 AG-UI canonical | The clients yield `ag_ui.core` events. Adapters implement `AGUIAgent` and emit standard interrupts. `core` does not import `reflex` or any extra (§1, §7.7). |
| Art. 2 Python / Reflex-native | Components use built-ins only. Renderers are Python functions (§10). |
| Art. 3 Secrets | Agents, clients and headers are `ClassVar`s or backend-only. `create_client` runs server-side. Headers are never logged or put in errors (§4.1, §4.4, §7.3, §9). |
| Art. 4 Non-blocking | Background streaming. Sync handlers run in a thread. The adapter contract forbids blocking (§6, §7.1). |
| Art. 5 Pure reducer | §11. Command transitions are also pure functions. |
| Art. 8 Stability / DX | The public surface is enumerated (§3). The quickstart is normative at 23 lines (§2). Deprecation policy (§12). |
| **Exceptions requested** | None. |

## Change History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-10-30 | Initial version |
| 1.1 | 2026-10-30 | TD v1.0 amendments A-1…A-7 (unreleased, so edited in place): quickstart with `ClassVar` and no `DeferredToolRequests` (23 lines); `ClassVar` rule for overrides; `max_client_tool_rounds` + `CLIENT_TOOL_LOOP_LIMIT`; PydanticAI output-type injection; LangGraph native interrupt keys, native multi-resume and cancelled-approval semantics; `RUN_FINISHED` cancelled outcome; Q-1…Q-5 resolved. |
| 1.2 | 2026-10-30 | Analyze fixes: lazy top-level re-exports (A-01); `AGENT_CONNECT_ERROR` → `AGENT_EXCEPTION` (A-06); `ChatMessage.is_error` (A-08); cancelled-outcome and client-tool transitions noted in §4.5 (A-02, A-09); `__version__` single source (A-11); `retry_run` side-effect note (A-12); A-17 accepted and noted in §4.6. |
| 1.3 | 2026-10-31 | §4.3 documents the background handler `drive_run` (Reflex rejects private handlers; TD v1.6). §4.4 adds `typed_shared_state()`, the typed accessor that REQ-016.6 requires and no section defined, and notes that hooks read configuration through `self.__class__` (Reflex binds them to a `StateProxy` during a run). Found in T-030 (spec drift rule). |
| 1.4 | 2026-10-31 | §3 clarifies that `reflex_agentkit.core.__all__` leaves out `__version__` (the package version lives only in the top-level module). Found in T-039. |
