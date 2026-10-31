# Agent clients

`AgentState` reads events from an `AgentClient`. Adapters implement `AGUIAgent`.

## Protocols

```python
@runtime_checkable
class AGUIAgent(Protocol):
    def run(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]: ...


@runtime_checkable
class AgentClient(Protocol):
    def stream(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]: ...
    async def aclose(self) -> None: ...
```

An `AGUIAgent` yields `ag_ui.core` events, from `RUN_STARTED` to exactly one
`RUN_FINISHED` or `RUN_ERROR`. It is cancelled by cancelling the consuming task, must
release resources in `finally` blocks, must not block the event loop, and reports
human-in-the-loop pauses as AG-UI standard interrupts (tool approvals with
`reason="tool_call"` and `toolCallId`), honoring `RunAgentInput.resume` on the next run.

An `AgentClient` yields validated events, skips invalid ones with a log record, raises
`AgentHTTPError` or `AgentStreamError` on transport failures (never a synthetic
`RUN_ERROR`), and closes its upstream within a second of being cancelled. `aclose()` is
idempotent.

Any object with a matching `run` method is an `AGUIAgent`; set it as `agent` and
`AgentState` wraps it in `InProcessAGUIClient`.

## HttpAGUIClient

```python
HttpAGUIClient(
    url: str,
    *,
    headers: Mapping[str, str] | Callable[[], Mapping[str, str]] | None = None,
    timeout: httpx.Timeout | float = httpx.Timeout(10.0, read=60.0),
    http_client: httpx.AsyncClient | None = None,  # yours: aclose() leaves it open
)
```

Talks to any AG-UI server. A callable `headers` is evaluated before each run. Headers are
never logged, never stored in state and never included in errors. One instance can serve
every session.

### The wire contract

The request is a `POST` with `Content-Type: application/json` and
`Accept: text/event-stream`, and the `RunAgentInput` as camelCase JSON:

| Field | Value |
|---|---|
| `threadId` | the thread |
| `runId` | a new UUID per run |
| `messages` | the whole history; assistant messages carry their `toolCalls`, client-tool results are `tool` messages |
| `state` | `shared_state` |
| `tools` | the client tools |
| `context`, `forwardedProps` | empty; extend them in `prepare_run_input` |
| `resume` | only when the run answers interrupts |

The response must be `2xx` with `Content-Type: text/event-stream`, one JSON event per SSE
`data:` field.

| Response | Result |
|---|---|
| non-`2xx` | `AgentHTTPError(status_code)`; the body (first 1 KiB) is logged at DEBUG only |
| other content type | `AgentStreamError(reason="content_type")` |
| no bytes for `timeout.read` | `AgentStreamError(reason="timeout")` |
| end of stream before `RUN_FINISHED` / `RUN_ERROR` | `AgentStreamError(reason="eof")` |

## InProcessAGUIClient

```python
InProcessAGUIClient(agent: AGUIAgent)
```

Runs `agent.run()` in the current event loop. Cancelling the run cancels the iteration,
and the agent sees `CancelledError`. This is what `agent: ClassVar = PydanticAIAgent(...)`
uses.

## How events are applied

| Events | Effect |
|---|---|
| `RUN_STARTED`, `RUN_FINISHED`, `RUN_ERROR` | `run_status`; `RUN_FINISHED.outcome` `interrupt` → `awaiting_input`, `cancelled` → `cancelled` |
| `STEP_STARTED`, `STEP_FINISHED` | `current_step` |
| `TEXT_MESSAGE_*` | `messages` |
| `TOOL_CALL_*` | `tool_calls` and `tool` messages |
| `STATE_SNAPSHOT`, `STATE_DELTA` | `shared_state` |
| `MESSAGES_SNAPSHOT` | replaces `messages` |
| `CUSTOM` | `custom_events` and `on_custom_event` |
| `REASONING_*` | `ChatMessage.reasoning` (encrypted values stay on the server) |
| `ACTIVITY_*`, `SUBAGENT_*`, `RAW` | accepted, no visible change |
| unknown types | skipped, with a DEBUG log record |
