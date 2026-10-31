# AgentState

```python
from reflex_agentkit import AgentState


class ChatState(AgentState, rx.State):
    agent: ClassVar = ...
```

`AgentState` is a Reflex state mixin. Put it first in the bases, before `rx.State`, as
Reflex requires for mixins.

## Configuration

All configuration is class-level. **Annotate every override as `ClassVar`**
(`agent: ClassVar = ...`, `flush_interval_ms: ClassVar = 30`); without the annotation
Reflex would turn the attribute into a state var and send it to the browser, and
`AgentState` refuses the class with a `ConfigurationError`.

| Name | Type | Default | Meaning |
|---|---|---|---|
| `agent` | `AgentClient \| AGUIAgent \| None` | `None` | The agent. An `AGUIAgent` (an adapter) is wrapped in `InProcessAGUIClient`. Required unless `create_client()` is overridden. |
| `client_tools` | `Sequence[ClientTool]` | `()` | Tools the agent can call that run in the app ([Client tools](client-tools.md)). |
| `shared_state_model` | `type[pydantic.BaseModel] \| None` | `None` | Validates every `shared_state` update. |
| `flush_interval_ms` | `int` | `50` | Most one state push per interval while streaming; `0` pushes every event. |
| `max_message_length` | `int` | `32_000` | Character limit for `send_message`. |
| `client_tool_timeout_s` | `float` | `30.0` | Default timeout of a client-tool handler. |
| `custom_events_limit` | `int` | `100` | How many CUSTOM events `custom_events` keeps. |
| `max_client_tool_rounds` | `int` | `8` | Most consecutive client-tool → follow-up rounds in one turn. |

Invalid configuration (no agent, a negative interval, two client tools with one name, a
`shared_state_model` that is not a Pydantic model) raises `ConfigurationError` when the
class is defined, so it fails at startup.

## State vars

App code reads these vars; only the library's handlers write them. They are sent to the
browser.

| Var | Type | Meaning |
|---|---|---|
| `messages` | `list[ChatMessage]` | The conversation, in order |
| `tool_calls` | `list[ToolCall]` | Every tool call of the thread, in start order |
| `pending_interrupt` | `PendingInterrupt \| None` | The current question (not tool approvals) |
| `shared_state` | `dict[str, Any]` | The agent's shared state, as JSON |
| `shared_state_stale` | `bool` | A delta failed to apply; true until the next snapshot |
| `run_status` | `RunStatus` | `idle`, `running`, `awaiting_input`, `cancelled` or `error` |
| `current_step` | `str` | Name of the active AG-UI step |
| `thread_id` | `str` | Created on the first run |
| `run_id` | `str` | The active run, or the last one |
| `error` | `str` | Message of the last error, `""` when none |
| `error_code` | `ErrorCode \| None` | Machine-readable code ([Errors](errors.md)) |
| `custom_events` | `list[CustomEventRecord]` | The last CUSTOM events |

Computed vars:

| Var | Definition |
|---|---|
| `is_running` | `run_status == "running"` |
| `awaiting_input` | `run_status == "awaiting_input"` |
| `pending_approvals` | calls with status `pending_approval`, in start order |
| `can_send` | `run_status` is `idle`, `cancelled` or `error` |

## Event handlers

Bind them to triggers (`on_click=ChatState.cancel_run`) or return them from your own
handlers. Handlers that start a run return at once; the run streams in a background task.
Every handler is safe to call at any time: calls that are not allowed in the current
status do nothing.

| Handler | Allowed when | Effect |
|---|---|---|
| `send_message(text)` | `can_send` | Adds a user message (stripped) and starts a run. Empty text does nothing; too long sets `MESSAGE_TOO_LONG`. |
| `approve_tool(call_id, edited_args=None)` | the call is `pending_approval` | Approves, optionally with edited arguments (a dict, or JSON text). Invalid edits set `INVALID_EDITED_ARGS` and keep the call pending. |
| `reject_tool(call_id, reason=None)` | the call is `pending_approval` | Rejects; the reason reaches the agent. |
| `respond_to_interrupt(payload)` | `pending_interrupt` is set | Answers the current question. JSON text is parsed; other text is sent as a string. |
| `cancel_run()` | `running` or `awaiting_input` | Stops the stream within a second, or leaves the pause (rejecting open approvals). |
| `new_thread()` | always | Cancels a running run, then starts a new, empty conversation. |
| `set_shared_state(value)` | not `running` | Replaces `shared_state` (validated). |
| `patch_shared_state(ops)` | not `running` | Applies RFC 6902 operations atomically. |
| `retry_run()` | `error` or `cancelled` | Runs the last user turn again. Backend tools may run again. |

The resume run after an approval or an answer starts by itself once every interrupt of
the pause has an answer. `drive_run()` is the background handler that streams a run; it
takes no arguments and does nothing unless a handler above scheduled a run. App code never
calls it.

## Hooks

Override these as plain methods. They are not event handlers: the browser cannot call
them, even when you override them.

| Hook | Default | Called |
|---|---|---|
| `create_client(self) -> AgentClient` | wraps `agent` | Once per run. Use it for per-session clients, such as auth headers. |
| `prepare_run_input(self, run_input) -> RunAgentInput` | identity | Before each run. Add `context`, `forwarded_props` or tools. |
| `async on_custom_event(self, name, value)` | no-op | After each CUSTOM event, under the state lock. Exceptions are logged. |
| `async on_run_end(self, status)` | no-op | Once per run, after the last push. |

`typed_shared_state()` returns `shared_state` as an instance of `shared_state_model`.

Hooks run on the event loop: they must not block. Inside a hook, read configuration
through `self.__class__`, not `type(self)` (during a run Reflex binds hooks to a state
proxy).
