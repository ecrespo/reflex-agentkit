# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Docs: an upstream status page that tracks the AG-UI, PydanticAI and LangChain docs
  submissions and explains how to act on each kind of response.

## [0.2.0] - 2026-10-31

### Added

- The documentation site is published to GitHub Pages from `main`
  (<https://blog.seraph.to/reflex-agentkit/>).
- The model is told when the user approves a tool call with edited arguments (REQ-035).
  Without this, models tended to report the edited result as a mistake or call the tool
  again with their own arguments.
  - `PydanticAIAgent` appends a notice to the edited call's result. Turn it off with
    `notify_edited_args=False`.
  - For LangGraph, `ApprovalDecision` gains `edited` and `tool_result(result)`. Build the
    `ToolMessage` from `decision.tool_result(...)`.

### Changed

- Approving with "edited" arguments identical to the proposed ones now records a plain
  approval, without `editedArgs` (REQ-013.3).
- `astral-sh/setup-uv` is pinned to a commit SHA in every workflow.
- Markdown-image exfiltration is an accepted residual risk; markdown images stay
  supported (TD v1.15).

## [0.1.0] - 2026-10-31

The first release. `0.1.0rc1` was published on 2026-10-31 as its release candidate.

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
- `AgentState`, the Reflex state mixin: `ClassVar` configuration validated when the class
  is defined (`ConfigurationError` names the attribute); public vars projected from a
  backend-only conversation (system messages, interrupt answers and encrypted reasoning
  never reach the browser); computed vars `is_running`, `awaiting_input`,
  `pending_approvals` and `can_send`; handlers `send_message`, `approve_tool`,
  `reject_tool`, `respond_to_interrupt`, `cancel_run`, `new_thread`, `set_shared_state`,
  `patch_shared_state` and `retry_run`; hooks `create_client`, `prepare_run_input`,
  `on_custom_event` and `on_run_end`; `typed_shared_state()` with `shared_state_model`
  validation of app writes and agent updates.
- The run driver behind `AgentState`: streaming in a background task with batched pushes
  (default 50 ms), cancellation within 1 s in the same worker or from another worker over
  a shared state manager, client-tool rounds with follow-up runs, local approvals and a
  loop limit, and silent stop when the conversation was replaced.
- `reflex_agentkit.adapters.pydantic_ai.PydanticAIAgent`: runs a PydanticAI agent in
  process through its AG-UI adapter; approval-required tools pause as AG-UI interrupts
  without declaring `DeferredToolRequests`; `deps` or a per-run `deps_factory`; extra
  `run_stream` arguments are forwarded. Importing an adapter without its extra raises
  `AdapterNotInstalledError` with the install command.
- `scripts/record_fixture.py` records event fixtures from real adapter runs.
- `reflex_agentkit.components`: `agent_chat` and its parts, built from Reflex built-ins
  only. `message_list` renders Markdown with raw HTML off, reasoning and a streaming
  indicator; `tool_call_card` shows a status badge and collapsible arguments and result;
  `composer` sends on Enter; `run_status_bar` has a cancel button; `approval_dialog`
  offers approve, edit-arguments and reject, or a form for generic interrupts with their
  queue position; `shared_state_panel` shows the JSON and a stale marker. `ToolRenderer`
  and `InterruptRenderer` replace the default card body or form. Every control has an
  accessible label.
- `agent_chat` is re-exported lazily from `reflex_agentkit`, and `reduce` from
  `reflex_agentkit.core`, as in API §3.
- `examples/quickstart/`: the 23-line quickstart, a uv workspace member, with an offline
  CI smoke job (`reflex compile --dry` with PydanticAI's `TestModel`).
- `examples/_shared/` (`examples-shared`): one model selection for every example —
  Claude by default, `AGENTKIT_MODEL=ollama:<model>` for a local Ollama model, and
  `AGENTKIT_MODEL=test` for an offline model — for PydanticAI and for LangChain chat
  models.
- `examples/pydantic_ai_dojo/` and `examples/langgraph_dojo/`: the five AG-UI Dojo demos
  (agentic chat, backend tool rendering, human in the loop, shared state, tool-based
  generative UI) as multi-page Reflex apps, with offline smoke tests and CI compile steps.
- Automatic releases: merging a new publishable `__version__` into `main` runs the tests,
  publishes to PyPI through trusted publishing and creates the `v<version>` tag and GitHub
  Release (`scripts/release_version.py` decides). Pre-releases go to PyPI too.
- `reflex_agentkit.adapters.langgraph`: `LangGraphAGUIAgent` runs a compiled LangGraph
  graph through the official ag-ui-langgraph integration with standard interrupts. It
  requires a checkpointer, serves every session from one instance, keeps the graph's
  messages out of `shared_state`, and resumes several interrupts with LangGraph's native
  map. `request_tool_approval` and `ApprovalDecision` put tool approvals in the same
  dialog as PydanticAI's. `legacy_interrupts=True` maps the older `on_interrupt` event.
- A draft upstream issue for ag-ui-langgraph's unconditional `fastapi` import
  (`docs/integrations/upstream-issues.md`).
- JSON Lines event fixtures and a replay runner that checks the state invariants after
  every step.
- A documentation site (MkDocs Material, `mkdocs.yml` and `docs/`): getting started,
  concepts, guides (your own UI, human in the loop, sidecar deployment, Ollama), the API
  reference, the security model and troubleshooting. CI builds it with `--strict`.
- Benchmarks under the `bench` marker: the reducer (NFR-01) and the flush lag with 20
  concurrent clients (NFR-04).
- A weekly workflow that tests against the newest allowed dependency versions and opens
  an issue when they fail.

### Fixed

- A tool call that a model sends in one chunk (Ollama through LangGraph) now shows its
  arguments in the approval dialog: a messages snapshot fills in the arguments of a call
  that streamed none. Found in the `0.1.0rc1` walkthrough.
- A `TOOL_CALL_RESULT` no longer moves a rejected or failed tool call back to `done`.
- A `MESSAGES_SNAPSHOT` now fills in the result of a tool call it keeps, so LangGraph tool
  calls end as `done` after their tool node runs.

### Security

- Reducer diagnostics are logged above DEBUG by code and event type only, since a failed
  patch can quote shared-state values.
- App-side shared-state patches are applied op by op under the 64 KiB cap and limited to
  256 operations, so `copy` ops cannot grow the document exponentially.
- `AgentState`'s hooks (`create_client`, `prepare_run_input`, `on_custom_event`,
  `on_run_end`) and `typed_shared_state`, and every override of them, are no longer
  registered as Reflex event handlers, so the browser cannot call them.
- The latest-dependencies workflow runs the newest, unvetted versions without a token or
  stored git credentials; a separate job reports failures.

[Unreleased]: https://github.com/ecrespo/reflex-agentkit/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/ecrespo/reflex-agentkit/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/ecrespo/reflex-agentkit/releases/tag/v0.1.0
