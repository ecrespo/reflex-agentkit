# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project skeleton: uv/hatchling packaging, lint, type and test configuration, and CI.
- `reflex_agentkit.core`: error hierarchy and `ErrorCode`, the `RunStatus` and
  `ToolCallStatus` enums, the value types (`ChatMessage`, `ToolCall`, `PendingInterrupt`,
  `CustomEventRecord`, `Diagnostic`) and the `ConversationState` aggregate, all with
  version-tolerant pickling.
- `reflex_agentkit.core.reducer`: the pure, total `reduce(state, event)` over all 31
  AG-UI 1.0 event types (lifecycle and `RUN_FINISHED` outcomes, text, tool calls,
  shared state, messages snapshots, reasoning, custom events) and `parse_event`, with
  diagnostics instead of exceptions.
- `reflex_agentkit.core.commands`: `begin_run`, `apply_approval` (with edited arguments),
  `apply_rejection`, `apply_interrupt_response`, `apply_cancel`,
  `apply_client_tool_result`, `all_answered`, `resume_entries` and `new_thread`.
- `client_tool` / `ClientTool`: client-side tools with a JSON Schema built from the type
  hints, `to_agui_tool()` and `invoke()` (sync handlers in a worker thread, timeout,
  failures returned as tool results).
- `RunInputBuilder`: builds `RunAgentInput` from the conversation (full history,
  encrypted reasoning before its assistant message, edited tool arguments, shared state,
  client tools, resume entries).
- Agent clients: the runtime-checkable `AGUIAgent` / `AgentClient` protocols and
  `AgentSource`; `HttpAGUIClient` (AG-UI over HTTP + SSE, static or per-run headers that
  are never logged, read timeout, typed `AgentHTTPError` / `AgentStreamError`, upstream
  closed on cancel) and `InProcessAGUIClient` (runs an agent object in the event loop,
  cancellation reaches the agent); an incremental SSE parser; invalid events are skipped
  with a log record.
- JSON Lines event fixtures and a replay runner that checks the state invariants after
  every step.
