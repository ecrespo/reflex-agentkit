# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

reflex-agentkit (PyPI `reflex-agentkit`, import `reflex_agentkit`, MIT) is the production UI
layer for Python AI agents, built on Reflex, speaking the AG-UI protocol. The repo is in the
**spec phase**: no source code, `pyproject.toml` or tests exist yet. Do not write
implementation code until the spec chain below is approved and Analyze has run.

**Read `specs/constitution.md` first.** It holds the non-negotiable rules (9 articles), the
stack constraints and the canonical glossary (run, thread, tool call, approval, interrupt,
shared state, adapter, client). Every artifact ends with a *Constitution check* section.

## Spec-driven process (spec-anchored)

Artifacts are produced in this order, **one per exchange, stopping for the maintainer's
approval after each** (follow the `spec-driven-design` skill):

1. `specs/constitution.md` — ratified v1.0
2. `specs/prd/agentkit-v0.1.md` — EARS criteria with IDs `REQ-NNN.k` — approved
3. `specs/api/agentkit-python-api-v1.md` — approved
4. `specs/technical/agentkit-architecture.md` — approved (pinned versions in DD-001)
5. `specs/data-model/agentkit-schema.md` — approved
6. `specs/plans/agentkit-phase-1.md` — approved (uv-only workflow, standard commands in §1.1)
7. `specs/tasks/agentkit-tasks.md` — approved (each task cites the REQ it implements; progress is tracked in the file)
8. Analyze gate — done, fixes applied (`specs/analysis/agentkit-v0.1-analyze.md`); then implement 3–5 tasks per batch

After v0.1 ships, any change to observable behavior or public API needs an approved delta
spec in `changes/<yyyy-mm>-<slug>/` first, which is folded into `specs/` once merged.
REQ IDs are never reused. Library versions (Reflex, `ag-ui-protocol`, `pydantic-ai`,
`ag-ui-langgraph`) must be verified with Context7 / web search and pinned in the Technical
Design — never from memory.

## Planned architecture (from the PRD)

- `reflex_agentkit.core` — AG-UI is the only internal event model. A pure
  `reduce(state, event) -> state` (no I/O, clock or randomness) is the sole path by which
  agent events change state. `AgentState` is a Reflex State mixin that streams via
  background events, batches pushes (default 50 ms flush) and supports real cancellation.
  `AgentClient` protocol with `HttpAGUIClient` (SSE via httpx) and `InProcessAGUIClient`
  (default; the "sidecar" deployment is just an AG-UI HTTP server + `HttpAGUIClient`).
- Human-in-the-loop uses AG-UI **standard interrupts**: `RUN_FINISHED` with
  `outcome.type == "interrupt"`, answered via `RunAgentInput.resume[]`. Tool approvals use
  PydanticAI v2's payload `{"approved": bool, "editedArgs"?: object, "reason"?: str}` for
  both adapters. `run_status` includes `awaiting_input`; tool status includes `rejected`.
- `reflex_agentkit.adapters.{pydantic_ai,langgraph}` — optional extras that translate
  *into* AG-UI. `core` must import and pass its tests with no extras installed.
- `reflex_agentkit.components` — Reflex built-in components only; no custom React/JS.
- `examples/` — `quickstart/` (≤ 30 non-blank, non-comment lines, CI-enforced) plus
  PydanticAI and LangGraph ports of the AG-UI Dojo demos.

## Rules that are easy to violate

- Nothing sensitive (clients, agent objects, HTTP headers, API keys) may live in a Reflex
  State var — those are serialized to the browser. Use backend-only storage.
- Never block the event loop; offload sync agent calls.
- `core` and `state` are written test-first; tests cite `REQ-NNN.k` in their name or
  docstring; coverage ≥ 85 % on each of `core` and `state`; JSON Lines event fixtures live
  in `tests/fixtures/`.
- `import reflex_agentkit.core` must never import `reflex`: the top-level `__init__.py`
  re-exports `AgentState`/components lazily (PEP 562 `__getattr__`).
- Toolchain mandated by the constitution: `uv`, `ruff` (lint + format), `mypy --strict`
  on `core` and `state`, `pytest` + `pytest-asyncio`, Python 3.11–3.13, hatchling `src/` layout.
  Add concrete commands here once `pyproject.toml` exists.
- Conventional Commits; CHANGELOG in Keep a Changelog format; everything in English.
- No telemetry, and no network calls beyond the agent endpoints the user configures.
