# Constitution — reflex-agentkit

> Version 1.1 · Ratified: 2026-10-30 · Last amended: 2026-10-30
> Scope: `github.com/ecrespo/reflex-agentkit` (package `reflex-agentkit`, import `reflex_agentkit`)
> Rigor level: **spec-anchored** — `specs/` is the current truth; changes enter through `changes/`.

This document holds the project's non-negotiable principles. Every later artifact (PRD,
API Spec, Technical Design, Data Model, Plan, Tasks) ends with a *Constitution check*
against it, and every pull request is reviewed against it. `CLAUDE.md` and `AGENTS.md`
point here so every agent session inherits these rules.

---

## Mission

> *Streamlit for agents was the prototype. This is the app.*

reflex-agentkit is the production UI layer for Python AI agents. It is built on Reflex
and speaks the AG-UI protocol, so it works with LangGraph, PydanticAI, Agno, LlamaIndex,
CrewAI and any other AG-UI-compatible backend. It fills the gap between Streamlit (a
prototype UI) and Next.js (a separate TypeScript codebase): one language, one process,
a bidirectional WebSocket that is already built in, and components that are Python objects.

## Non-goals

These are out of scope. A proposal that moves toward one of them needs a constitutional
amendment, not a feature spec.

| Non-goal | Boundary |
|---|---|
| Agent framework | We do not orchestrate, plan, or call LLMs. LangGraph, PydanticAI, etc. own that. |
| "AI that generates Reflex apps" | Reflex Inc.'s builder owns that. We are the inverse: Reflex apps that *serve* agents. |
| General chat widget library | `reflex-assistant-ui` covers rich chat rendering. It may become an optional rendering backend (v0.2+), never a v0.1 dependency. |
| Observability / tracing UI | Reserved for the future project `reflex-agentscope`. |
| MCP host | Reserved for the future project `reflex-mcphost`. |
| Browser-side agents | No LangChain.js, LangGraph.js or any agent runtime in the frontend. |

---

## Articles

### Art. 1 — AG-UI is the canonical event model
THE SYSTEM SHALL represent all agent activity inside `reflex_agentkit.core` exclusively as
AG-UI protocol events. Framework adapters SHALL translate *into* AG-UI events and SHALL NOT
mutate `AgentState` through any other path. `reflex_agentkit.core` SHALL import, and pass
its full test suite, with no optional extra (`[pydantic-ai]`, `[langgraph]`, …) installed.
*Rationale: protocol-first is the product strategy. A side channel for one framework turns
the library into a LangGraph UI and loses every other backend.*

### Art. 2 — Python only, Reflex-native, agents server-side
THE SYSTEM SHALL ship no custom React/JavaScript components and no JS/npm dependencies in
v0.1. All UI SHALL be built from Reflex's built-in components and default theme. Agents
SHALL execute only on the server (in the Reflex backend process or a server-side sidecar),
never in the browser.
*Rationale: the "no TypeScript tax" promise is the reason to choose this library. Custom
React wrappers bring back the toolchain users are trying to escape.*

### Art. 3 — Secrets never reach the client; no telemetry
THE SYSTEM SHALL NOT place API keys, credentials, auth headers or client configuration
objects in any Reflex State var, because State vars are serialized to the browser. Clients
and agents SHALL be held in server-only storage (backend-only vars or a server-side
registry keyed by session). The library SHALL NOT collect telemetry or make any network
call other than those to the agent endpoint the user configures. A test SHALL assert that
the serialized `AgentState` of a configured app contains no configured secret value.
*Rationale: one leaked key in a WebSocket frame is a security incident for every adopter.
A UI library that phones home loses trust it cannot win back.*

### Art. 4 — Never block the event loop; streams are bounded and cancellable
THE SYSTEM SHALL run all agent I/O inside async code paths (Reflex background events) and
SHALL offload any synchronous agent call (`asyncio.to_thread` or a sidecar) so that it
never blocks the event loop. Streaming deltas SHALL be batched before they are pushed to
the client (configurable flush interval). Cancelling a run SHALL close the upstream stream
or task within a bounded time that the PRD defines. A test with a deliberately slow fake
agent SHALL prove that a second client stays responsive during a run.
*Rationale: Reflex serves every client from one event loop per worker. A single blocking
agent call freezes every user's UI, and that is exactly the failure that keeps "Python UI
for agents" from looking production-grade.*

### Art. 5 — Event handling is a pure, replayable reducer
THE SYSTEM SHALL implement AG-UI event handling as a pure function
`reduce(state, event) -> state`, with no I/O, no clock reads and no randomness. State
changes driven by the agent SHALL flow only through this reducer. Every AG-UI event type
the library supports SHALL have at least one recorded JSON Lines fixture under
`tests/fixtures/`, and the fixtures SHALL include out-of-order and error sequences.
*Rationale: streaming UIs fail in ways that are hard to reproduce. A pure reducer turns
every bug report into a replayable fixture and a one-line regression test.*

### Art. 6 — Testing discipline
THE TEAM SHALL write tests **before** the implementation for `reflex_agentkit.core` and
`reflex_agentkit.state` (the reducer, the clients, `AgentState` and the run driver). Components, adapters and examples SHALL ship
their tests in the same pull request as the code. Every test that verifies an acceptance
criterion SHALL cite its ID (`REQ-NNN`, or `REQ-NNN.k` for a single criterion) in its name
or docstring. Line coverage of `reflex_agentkit.core` and of `reflex_agentkit.state` SHALL each stay
≥ 85 % or CI fails. Each
example app SHALL have a smoke test that compiles it.
*Rationale: TDD where the logic is subtle (event ordering, cancellation, patches);
pragmatism where the code is mostly composition. Criterion IDs keep the chain from
requirement to test auditable.*

### Art. 7 — Code quality gate
THE TEAM SHALL keep the CI gate green on every merge to `main`: `ruff check`,
`ruff format --check`, `mypy --strict` on `reflex_agentkit.core` and `reflex_agentkit.state`
(and `mypy` on the rest),
and `pytest` on Python 3.11, 3.12 and 3.13. No merge with a failing gate, and no
`# type: ignore` or `# noqa` without an inline reason.
*Rationale: a library is only as good as its weakest supported interpreter. Strict typing
on the core is what lets adopters trust the public types.*

### Art. 8 — Public API stability and developer experience
THE PROJECT SHALL follow Semantic Versioning starting at `0.1.0`. During `0.x`, a breaking
change to the public API (`AgentState` vars and event handlers, component signatures, the
`AgentClient` protocol, adapter entry points, and anything exported from
`reflex_agentkit.__all__`) SHALL be preceded by a `DeprecationWarning` that lasts at least
one minor release. It SHALL also have a CHANGELOG entry and an approved delta spec. The
`examples/quickstart/` app SHALL stay ≤ 30 lines (excluding blank lines and comments) and
SHALL deliver streaming chat, visible tool calls and a human-approval dialog. CI SHALL
enforce both the line limit and the compile check.
*Rationale: the 30-line quickstart is the product's first impression. Silent breakage is
how a 0.x library loses its early adopters.*

### Art. 9 — Spec-anchored process and project hygiene
THE TEAM SHALL NOT implement any change to observable behavior or to the public API before
an approved delta spec exists under `changes/<yyyy-mm>-<slug>/`. Pure bug fixes that
restore specified behavior, and refactors with no observable change, are exempt. Once a
delta spec is approved and merged, it SHALL be folded into `specs/`. Commits SHALL follow
Conventional Commits. `CHANGELOG.md` SHALL follow Keep a Changelog. All code, comments,
docs, specs and commit messages SHALL be in English.
*Rationale: specs that drift from code are worse than no specs. The delta-spec gate keeps
`specs/` true, and Conventional Commits keep the CHANGELOG cheap.*

---

## Stack constraints

Decided; these are not reopened per feature. Exact versions are verified and pinned in the
Technical Design (`specs/technical/agentkit-architecture.md`), not from memory.

| Area | Constraint |
|---|---|
| Language | Python ≥ 3.11; CI matrix 3.11 / 3.12 / 3.13 |
| UI framework | Reflex, current stable at design time (version range pinned in Tech Design) |
| Protocol | AG-UI (`ag-ui-protocol` Python package for types/encoding; whether it is a hard dependency is decided in the PRD/Tech Design) |
| HTTP client | `httpx` (async) for the SSE client |
| State patches | JSON Patch, RFC 6902 |
| Packaging | `src/` layout, `pyproject.toml`, hatchling build backend, `uv` for env/lock |
| Optional extras | `[pydantic-ai]`, `[langgraph]`; granularity decided in the PRD/Tech Design |
| Quality | `ruff` (lint + format), `mypy --strict` on `core` and `state`, `pytest` + `pytest-asyncio`, coverage via `pytest-cov` |
| CI / release | GitHub Actions; PyPI release on tag via trusted publishing (OIDC) |
| Docs | MkDocs Material under `docs/`; README, CONTRIBUTING, CHANGELOG at the root |
| License | MIT |

## Glossary (canonical terms; use these spellings in every artifact)

| Term | Meaning |
|---|---|
| **run** | One AG-UI execution, delimited by `RUN_STARTED` … `RUN_FINISHED` / `RUN_ERROR`. Identified by `run_id`. |
| **user message** | A message with AG-UI role `user`: the human's turn. Never "human message" as a role name. |
| **thread** | A conversation made of one or more runs. Identified by `thread_id` (maps to AG-UI `threadId`). |
| **tool call** | An AG-UI `TOOL_CALL_*` sequence; has a `call_id` and a status. |
| **approval** | A human decision (approve / approve-with-edited-args / reject) on a tool call in status `pending_approval`. |
| **interrupt** | A human-in-the-loop request raised by the agent (e.g., LangGraph `interrupt()`), exposed as `pending_interrupt`. Answered with `respond_to_interrupt`. |
| **shared state** | The JSON document mirrored from `STATE_SNAPSHOT` / `STATE_DELTA`; exposed as `shared_state`. |
| **adapter** | An optional module that makes a framework object (PydanticAI `Agent`, compiled LangGraph graph) behave as an AG-UI agent. |
| **client** | An `AgentClient` implementation that produces AG-UI events for the reducer (`HttpAGUIClient`, `InProcessAGUIClient`). |

## Amendments

| Date | Article | Change | Reason | Approved by |
|---|---|---|---|---|
| 2026-10-30 | All | Initial ratification (v1.0) | Project kickoff | Ernesto Crespo |
| 2026-10-30 | Art. 6, 7; Stack; Glossary | v1.1 clarification: test-first, coverage and strict-typing gates cover `reflex_agentkit.state` as well as `core`; glossary adds **user message** | Analyze A-04, A-10: `AgentState`/`RunDriver` live in `state` and were outside the gates | Ernesto Crespo |

To amend: open a PR that edits this file, bumps the version (minor for clarification,
major for adding, removing or reversing an article), adds a row here, and states which
existing specs are affected.

## Constitution check (required in every artifact)

At the end of every PRD, API Spec, Tech Design, Data Model and Plan, add a 3–5 line section
that lists which articles apply and how the artifact complies with each. If the artifact
needs an exception, it SHALL name the article, the reason and the expiry. An exception
with no written justification is a violation.
