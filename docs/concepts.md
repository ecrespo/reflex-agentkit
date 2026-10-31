# Concepts

reflex-agentkit uses the vocabulary of the AG-UI protocol. These are the words the rest of
the docs use.

## AG-UI events

An agent talks to the UI through a stream of AG-UI events: `RUN_STARTED`, text deltas
(`TEXT_MESSAGE_CONTENT`), tool calls (`TOOL_CALL_START`, `TOOL_CALL_ARGS`, …), state
updates (`STATE_SNAPSHOT`, `STATE_DELTA`) and, at the end, `RUN_FINISHED` or `RUN_ERROR`.
AG-UI is the only event model inside the library: adapters translate *into* it.

A pure function, `reduce(state, event) -> state`, is the only way events change the
conversation. It does no I/O and never raises; malformed or out-of-order events become
diagnostics in the log. That is what makes the behavior reproducible and testable.

## Thread and run

- A **thread** is one conversation. Its `thread_id` is created on the first run and kept
  until `new_thread()`.
- A **run** is one agent turn: the input (the whole history, the shared state and the
  client tools) goes to the agent, and its events stream back. Each run has a new
  `run_id`. There is at most one run in flight per browser session.

`run_status` tells you where the conversation is:

| Status | Meaning | Next |
|---|---|---|
| `idle` | Nothing running | `send_message` starts a run |
| `running` | The agent is streaming | `cancel_run` stops it |
| `awaiting_input` | The agent paused for approvals or answers | answer them, or `cancel_run` |
| `cancelled` | The user stopped the run | `send_message` or `retry_run` |
| `error` | The run failed; `error` and `error_code` say why | `send_message` or `retry_run` |

## Messages

`messages` holds the conversation as `ChatMessage` values with AG-UI roles: `user`,
`assistant` and `tool`. An assistant message is `streaming` until its last delta.

## Tool calls

A **tool call** is a request from the model to run a tool. Each one is a `ToolCall` in
`tool_calls`, rendered as a card under the message that issued it, with a status:
`streaming` → `running` → `done`, or `pending_approval`, `rejected` and `error`.

- A **backend tool** runs in the agent (a PydanticAI tool, a LangGraph tool node). The UI
  only shows it.
- A **client tool** runs in your Reflex app. The agent sees its definition; when it calls
  it, the run ends, the library runs your handler on the server and starts a follow-up
  run with the result. See [Client tools](reference/client-tools.md).

## Approvals and interrupts

Human-in-the-loop uses AG-UI **standard interrupts**: the run finishes with
`outcome.type == "interrupt"` and a list of interrupts; `run_status` becomes
`awaiting_input`; the next run carries the answers in `RunAgentInput.resume`.

- An **approval** is an interrupt for a tool call (`reason == "tool_call"`). The call is
  `pending_approval` until `approve_tool` (optionally with edited arguments) or
  `reject_tool`.
- A **generic interrupt** is any other question from the agent, for example LangGraph's
  `interrupt("How many nights?")`. It is in `pending_interrupt` until
  `respond_to_interrupt(answer)`.

When every interrupt of a pause has an answer, the resume run starts by itself.
`cancel_run` while paused rejects the open approvals and cancels the questions.

## Shared state

**Shared state** is a JSON object both sides can see: the agent sends it with
`STATE_SNAPSHOT` and `STATE_DELTA` (JSON Patch), and every run sends it back as the AG-UI
`state`. It is in `shared_state`. The app can change it between runs with
`set_shared_state` or `patch_shared_state`. With `shared_state_model` set to a Pydantic
model, every update is validated, and `typed_shared_state()` returns an instance.

## Adapter and client

- An **adapter** turns an agent framework into an AG-UI event source (an `AGUIAgent`):
  `PydanticAIAgent`, `LangGraphAGUIAgent`.
- A **client** is what `AgentState` reads events from (an `AgentClient`):
  `InProcessAGUIClient` runs an `AGUIAgent` in the same event loop (the default when you
  set `agent` to an adapter), and `HttpAGUIClient` talks to an AG-UI server over HTTP and
  Server-Sent Events (the [sidecar](guides/sidecar.md)).

## Streaming and batching

Runs stream in a Reflex background task, so the page stays responsive and other users are
not blocked. State pushes are batched: at most one every `flush_interval_ms` (50 ms by
default), which keeps the WebSocket quiet while tokens arrive quickly.
