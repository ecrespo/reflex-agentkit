# Integration prompts — reflex-agentkit

Part of the cross-project integration map (2026-10-31). The five integrations, ranked by
value: **#1 AG-UI prismal → agentkit** (this file), #2 OTel → agentlens, #3 ACP/A2A
Umbral ⇄ prismal, #4 JSON-RPC Umbral → xtermjs, #5 shared MCP host. Each repository
that an integration touches carries its own `docs/integration-prompts.md`; the prompts
are written to be handed to a coding agent as-is, after the SDD artifacts they name exist.

Counterpart: `prismal-server/docs/integration-prompts.md` (the AG-UI endpoint).

---

## Prompt I1-A · `PrismalAgent` adapter over AG-UI

**Preconditions:** T-006 … T-030 of `specs/tasks/agentkit-tasks.md` are done (reducer,
`HttpAGUIClient`, `RunDriver`, `AgentState`), and `prismal-server` serves
`POST /threads/{id}/agui` as an AG-UI 1.0 SSE stream (its prompt I1-B).

```
You are working in reflex-agentkit (Python 3.12+, uv, strict mypy, pytest, Reflex
0.10.x). Read specs/constitution.md, specs/prd/agentkit-v0.1.md §6 (adapters),
specs/technical/agentkit-architecture.md §4 (adapter contract) and
src/reflex_agentkit/adapters/pydantic_ai.py as the reference adapter.

Goal: add a third adapter, `reflex_agentkit.adapters.prismal.PrismalAgent`, that
turns a running prismal-server into an agent usable by `AgentState` with zero
TypeScript and no change to the core reducer.

Scope:
1. `adapters/prismal.py`: a class built on `HttpAGUIClient` that targets
   `{base_url}/threads/{thread_id}/agui`, creates the thread lazily via
   `POST /threads`, forwards `RunAgentInput` unchanged, and carries the server's
   auth header from an env var or constructor argument (never from client state).
2. Tolerances the reducer must accept, because prismal's translator deviates
   from the spec on purpose (see prismal/prismal/events/agui.py docstring):
   - there is NO `INTERRUPT` event: a LangGraph interrupt arrives as
     `RUN_FINISHED.outcome = {"type": "interrupt", "interrupts": [...]}` —
     map it to the same approval flow the PydanticAI adapter uses for
     deferred tool calls;
   - there is NO `USAGE` event: usage arrives as `CUSTOM prismal.usage` AND as
     `RUN_FINISHED.usage`; surface it on `AgentState.last_usage`;
   - `SUBAGENT_STARTED/FINISHED/ERROR` events: render as nested status rows,
     never drop them;
   - `CUSTOM prismal.routing` / `prismal.decision`: keep in
     `conversation.custom_events`, do not render by default.
   Implement these as adapter-level event pre-processing, NOT as special cases
   in core/reducer.py (the reducer stays protocol-pure, per constitution Art. 3).
3. Optional extra `reflex-agentkit[prismal]` in pyproject.toml with
   `prismal-sdk>=0.2` as the only dependency; keep the import guard pattern of
   adapters/_require.py.
4. Tests: a recorded fixture of a real prismal-server run (fake-LLM mode) under
   tests/fixtures/prismal/, a contract test that replays it through the reducer,
   and a unit test per tolerance above. Follow the fixture recorder of T-035.
5. Docs: README section "Using prismal as the backend" with the 30-line
   quickstart; CHANGELOG entry under Unreleased.

Acceptance (EARS):
- WHEN a prismal-server run ends with an interrupt outcome THE SYSTEM SHALL show
  the approval dialog and resume the run with the user's decision through
  `RunInputBuilder`.
- THE SYSTEM SHALL pass the existing reducer property tests unchanged.
- IF `prismal-sdk` is not installed THEN importing `reflex_agentkit.adapters.prismal`
  SHALL raise the same `MissingExtraError` the other adapters raise.

Out of scope: changing prismal's translator; WebSocket transport; multi-tenant auth.
Record every undecided point as a delta under specs/ before merging.
```

## Prompt I1-C · Upstream listing after release

```
After reflex-agentkit v0.1 is on PyPI with the prismal, PydanticAI and LangGraph
adapters: open a PR to https://github.com/ag-ui-protocol/ag-ui adding
reflex-agentkit to the clients table of docs/integrations (Python / Reflex),
with the quickstart link and the three supported backends. Prepare the same for
PydanticAI's and LangGraph's "UI integrations" docs pages. Keep the wording
factual; link the recorded demo video from the component gallery.
```
