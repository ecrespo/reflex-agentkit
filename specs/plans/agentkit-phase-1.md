# reflex-agentkit v0.1 — Implementation Plan (Phase 1: v0.1.0)

## Metadata

| Field | Value |
|---|---|
| **Author** | Ernesto Crespo (`ecrespo`) |
| **Status** | `APPROVED` (2026-10-30) |
| **Version** | 1.3 |
| **Date** | 2026-10-30 |
| **PRD** | [v1.1](../prd/agentkit-v0.1.md) |
| **API Spec** | [v1.1](../api/agentkit-python-api-v1.md) |
| **Tech Design** | [v1.0](../technical/agentkit-architecture.md) |
| **Data Model** | [v1.0](../data-model/agentkit-schema.md) |
| **Governed by** | [`specs/constitution.md`](../constitution.md) v1.0 |

---

## 1. Implementation Summary

The plan has **nine work packages (WP0–WP8)** that build inside-out, following the TD
layering:
1. foundation;
2. the pure core;
3. the clients;
4. the Reflex state engine;
5. the PydanticAI adapter;
6. the components and the quickstart;
7. the LangGraph adapter;
8. the Dojo examples;
9. hardening, docs and release.

Every WP ends with something verifiable in CI. Two pre-releases to PyPI (no TestPyPI, a
maintainer decision of 2026-10-31) validate packaging early: **`0.1.0a1`** once the quickstart works end-to-end (end of WP5) and
**`0.1.0rc1`** before the final release.

**uv is the only package and project manager** (Constitution stack constraints).
- No `pip`, `poetry`, `pip-tools`, `requirements*.txt` or `setup.py`.
- `uv.lock` is committed.
- Development tools live in `[dependency-groups]`.
- Builds use `uv build` (hatchling backend) and releases use `uv publish` with PyPI
  trusted publishing.
- CI installs uv through `astral-sh/setup-uv`, with caching enabled.
- `pip install reflex-agentkit` stays the *end-user* install command in the README,
  alongside `uv add reflex-agentkit`.

**Estimated total duration:** ≈ 54 maintainer-days, about 11 weeks of part-time work (solo maintainer). The
estimates already include the ×1.5 factor; see §5.
**Team:** 1 maintainer, with Claude Code executing tasks in batches of 3–5 (Art. 9,
skill rule).
**Target date for `v0.1.0`:** 2027-01-15 (indicative; it depends on part-time
availability).

### 1.1 Standard commands (normative for every WP; copied into CLAUDE.md in WP0)

| Purpose | Command |
|---|---|
| Create or refresh the env (all extras plus dev group) | `uv sync --all-extras` |
| Core-only env (no extras; Art. 1 check) | `uv sync --no-dev --group test` |
| Lint / format check | `uv run ruff check .` · `uv run ruff format --check .` |
| Type check | `uv run mypy` (strict on `reflex_agentkit.core` and `reflex_agentkit.state` via `[tool.mypy]` overrides) |
| Tests (default, with coverage) | `uv run pytest` |
| A single test | `uv run pytest tests/unit/core/test_reducer.py::test_name -q` |
| Tests by REQ | `uv run pytest -k "REQ_013"` (test names embed the REQ ID with `_` separators) |
| Slow / bench / redis markers | `uv run pytest -m "slow or redis"` · `uv run pytest -m bench` |
| Run an example | `cd examples/quickstart && uv run reflex run` |
| Add a dependency (maintainer only, with a delta or TD note) | `uv add <pkg>` · `uv add --optional pydantic-ai <pkg>` · `uv add --group dev <pkg>` |
| Upgrade the lock | `uv lock --upgrade` (or `--upgrade-package <pkg>`) |
| Build | `uv build` (writes sdist and wheel to `dist/`) |
| Publish (CI only) | `uv publish --trusted-publishing always` (PyPI only) |
| Docs | `uv run mkdocs serve` · `uv run mkdocs build --strict` |

### 1.2 `pyproject.toml` layout (decided here; implemented in WP0)

- `[project]`
  - `requires-python = ">=3.11,<3.14"`;
  - runtime dependencies per TD DD-001;
  - `[project.optional-dependencies]`: `pydantic-ai`, `langgraph`, `all`. These are
    end-user extras, so they stay optional-dependencies, not groups.
- `[dependency-groups]`:
  - `test` (pytest, pytest-asyncio, pytest-cov, hypothesis, uvicorn);
  - `lint` (ruff, mypy);
  - `docs` (mkdocs-material);
  - `redis` (redis);
  - `dev = [{include-group = "test"}, {include-group = "lint"}, {include-group = "docs"}]`.
  - `[tool.uv] default-groups = ["dev"]`.
- `[build-system]`: `requires = ["hatchling"]`, `build-backend = "hatchling.build"`.
  `[tool.hatch.build.targets.wheel] packages = ["src/reflex_agentkit"]`.
- The version comes from `src/reflex_agentkit/__init__.py` through `[tool.hatch.version]`.
  It is bumped by editing that file in the release PR. The literal is the single source of
  the version (no `importlib.metadata` lookup).
- The top-level `__init__.py` uses lazy (PEP 562) re-exports for the Reflex-dependent
  names, so `import reflex_agentkit.core` never imports `reflex` (API §1).
- Each example under `examples/*` is a **uv workspace member**
  (`[tool.uv.workspace] members = ["examples/*"]`) with its own `pyproject.toml` and a
  workspace dependency `reflex-agentkit = { workspace = true }`. One `uv.lock` covers the
  library and all examples, and `uv run --package quickstart reflex run` works from the
  root.

## 2. Prerequisites

| Prerequisite | Owner | Status | Deadline |
|---|---|---|---|
| Constitution, PRD, API, TD and Data Model approved | Maintainer | ☑ Done (2026-10-30) | — |
| Tasks file approved and Analyze gate run | Maintainer | ☐ Pending | before WP0 |
| GitHub repo `ecrespo/reflex-agentkit` (remote exists) | Maintainer | ☑ Exists | — |
| PyPI name `reflex-agentkit` (404 = available, checked 2026-10-30) | Maintainer (`seraph13`) | ☐ Register a **pending trusted publisher** on PyPI (no TestPyPI): owner `ecrespo`, repository `reflex-agentkit`, workflow `release.yml`, environment `pypi` | before WP5 end (`0.1.0a1`) |
| GitHub environment `pypi` (no required reviewers: releases are automatic) | Maintainer | ☐ Pending | before WP5 end |
| uv ≥ 0.11 locally (0.11.7 installed) | Maintainer | ☑ | — |
| Docker for the Redis test container (installed) | Maintainer | ☑ | WP3 |
| `ANTHROPIC_API_KEY` for manual demo runs only (never in CI) | Maintainer | ☐ | WP5 |
| Ollama with one tool-calling model pulled (e.g. `ollama pull qwen3`), for the documented local option | Maintainer | ☐ (ollama installed) | WP7 |

## 3. Work Packages

Legend: estimates are maintainer-days, already ×1.5. **[P]** means the WP can run in
parallel with the previous one once its own dependencies are met. Each WP lists the REQs
it closes. The Tasks file (`specs/tasks/agentkit-tasks.md`) splits every WP into
agent-executable tasks of 0.5–1.5 days, with a test-first order for `core`.

---

### WP0 — Foundation and CI (≈ 3 d)

**Goal:** an empty-but-real package that installs with uv, plus a CI pipeline that enforces
the constitution from the first commit.

| ID | Work item | Est. | Depends | REQs / Art. |
|---|---|---|---|---|
| WP0-01 | `pyproject.toml` (§1.2), `src/` skeleton matching TD §5.1, `py.typed`, `__version__`, `uv lock` | 0.5 d | — | 031.1 |
| WP0-02 | Ruff, mypy (strict override for `reflex_agentkit.core.*` and `reflex_agentkit.state.*`) and pytest config (asyncio mode, markers `slow`/`redis`/`bench`, coverage ≥ 85 % on core and on state) | 0.5 d | 01 | Art. 6–7 |
| WP0-03 | GitHub Actions `ci.yml`: `lint`, `typecheck`, `test` matrix 3.11–3.13 (`uv sync --locked`), `core-no-extras` (import check: `reflex_agentkit.core` imports neither `reflex` nor extras) | 1 d | 02 | 031.2, 032.1 |
| WP0-04 | Upstream contract tests (TD §8.4 items 1 and 4; the adapter items are added in WP4/WP6) | 0.5 d | 02 | TD §8.4 |
| WP0-05 | Repo hygiene: `AGENTS.md` (points to the constitution), `CLAUDE.md` commands section from §1.1, `CONTRIBUTING.md` skeleton (uv workflow, Conventional Commits, delta-spec gate), `CHANGELOG.md` (Keep a Changelog, `Unreleased`), fix the README title typo (`reflex-agenkit`) | 0.5 d | 01 | 033.1, Art. 9 |

**Done when:** `uv sync --locked` works on a clean clone. CI is green on all jobs on a PR.
`uv build` produces a wheel that imports.

---

### WP1 — Pure core (≈ 14.5 d) · test-first

**Goal:** `reflex_agentkit.core` without I/O: value types, reducer, commands, run-input
builder, client tools, errors. This is the critical path and the most heavily tested part.

| ID | Work item | Est. | Depends | REQs |
|---|---|---|---|---|
| WP1-01 | `errors.py`, enums, `JsonValue` aliases, value types (DM §3), tolerant pickle mixin (DM §8) | 1 d | WP0 | DM §2–3, §8 |
| WP1-02 | `ConversationState` + `with_()` helper + derived indexes + invariant checker (test-only helper) | 1 d | 01 | DM §3.10, §4 |
| WP1-03 | Fixture loader/runner (DM §10: header, placeholders, `$command` lines, partial-match `expect`) | 1 d | 02 | 005.3 |
| WP1-04 | `_patch.py` façade over `jsonpatch` (atomic) | 0.5 d | 01 | 016.2–3 |
| WP1-05 | Reducer: lifecycle, steps, unknown, ignored and invalid events, stale-run filtering | 1.5 d | 03 | 004, 010.1–3, 012 |
| WP1-06 | Reducer: text messages (incl. CHUNK, implicit, end-of-run close) | 1 d | 05 | 008 |
| WP1-07 | Reducer: tool calls (incl. CHUNK, RESULT, invalid args, size cap, dirty-args) | 1.5 d | 05 | 009 |
| WP1-08 | Reducer: state snapshot/delta, `MESSAGES_SNAPSHOT`, CUSTOM ring, reasoning | 1.5 d | 04, 06, 07 | 010.4–5, 011, 016.1–4 |
| WP1-09 | Reducer: `RUN_FINISHED` outcomes (success, interrupt → pending approvals / generic queue, cancelled) | 1 d | 07 | 004.1–2, 013.1, 014.1 |
| WP1-10 | Commands: `begin_run`, approvals, rejection, interrupt answers, cancel (running and paused), client-tool result, `all_answered`, `resume_entries` | 1.5 d | 09 | 001, 002, 013, 014, 015, 018.2 |
| WP1-11 | `RunInputBuilder` (egress mapping DM §7.3) + round-trip property | 1 d | 10 | 001.2, 011.2, 016.7 |
| WP1-12 | `tools.py`: `client_tool` decorator, schema from hints, `invoke()` (async/sync offload, timeout) | 1 d | 01 | 018.1, 018.4–5, 024.2 |
| WP1-13 | Hypothesis properties: totality, determinism, INV-1…12 over random sequences | 1 d | 10 | 005.1–2, DM §4 |

**Done when:** all reducer and command fixtures pass. Core coverage is ≥ 85 %, `mypy
--strict` is clean, and the property tests run 500 examples each in under 10 s. The
reducer benchmark meets NFR-01, or the DM §5 escape hatch is applied.

---

### WP2 — Clients (≈ 4 d) · [P] with WP1-05 onward

**Goal:** transport to AG-UI agents, over HTTP SSE and in-process.

| ID | Work item | Est. | Depends | REQs |
|---|---|---|---|---|
| WP2-01 | `AgentClient` / `AGUIAgent` protocols, plus event validation and skip-with-warning | 0.5 d | WP1-01 | 021.1, 012.3 |
| WP2-02 | Pure SSE parser (multi-line data, comments, CRLF, partial chunks) | 0.5 d | 01 | 021.2 |
| WP2-03 | Fake AG-UI server fixture (Starlette + uvicorn on an ephemeral port; scripted streams; records disconnects) | 1 d | — | TD DD-010 |
| WP2-04 | `HttpAGUIClient`: request composition, status, content-type, timeouts, EOF, cancel closes connection, header hygiene | 1.5 d | 02, 03 | 021.2–4, 021.6, 007.2, 004.4 |
| WP2-05 | `InProcessAGUIClient`: cancel propagates `CancelledError`, exceptions → `AgentStreamError`/connect | 0.5 d | 01 | 021.5, 007.3 |

**Done when:** the integration tests against the fake server pass in CI, including "the
server observed the disconnect within 1 s".

---

### WP3 — Reflex state engine (≈ 8.5 d)

**Goal:** `AgentState` streams, batches, cancels and runs client tools, all verified
without a browser.

| ID | Work item | Est. | Depends | REQs |
|---|---|---|---|---|
| WP3-01 | Spike (≤ 0.5 d): the Reflex in-process testing approach (TD OQ-1). Decide the `StateAccess` fake vs. Reflex helper split. | 0.5 d | WP0 | — |
| WP3-02 | `StateAccess` port + in-memory fake; `RunRegistry` | 0.5 d | WP1-02 | TD §5.2 |
| WP3-03 | `RunDriver`: pump task + queue, flush-on-deadline batching, terminal flush, ownership check, diagnostics logging | 2 d | 02, WP2-01 | 006, 004.4, 026.2, 027 |
| WP3-04 | `RunDriver`: cancellation (registry path and flag path), discard after cancel | 1 d | 03 | 007.1–5 |
| WP3-05 | `RunDriver`: client-tool rounds, local approvals, loop limit, handler errors and timeouts | 1 d | 03, WP1-12 | 018, DD-009 |
| WP3-06 | `AgentState` mixin: ClassVar config validation in `__init_subclass__`, public vars, computed vars, projection, `_pending_start` claim | 1.5 d | 01, 03 | API §4.1–4.2, 003, 025.1 |
| WP3-07 | `AgentState` handlers + hooks (`create_client`, `prepare_run_input`, `on_custom_event`, `on_run_end`), shared-state writes | 1 d | 06 | API §4.3–4.4, 017, 020 |
| WP3-08 | Cross-cutting tests: secret leak (REQ-025.2), responsiveness with a slow agent (REQ-024.1), multi-worker cancel with the Redis container (`redis` marker; CI service container) | 1 d | 07 | 025.2, 024.1, 007.6 |

**Done when:** the driver and state tests pass, the `redis` CI job is green, and REQ-007.6
is promoted from SHOULD to MUST (delta noted in the PRD change history, since it is
unreleased).

---

### WP4 — PydanticAI adapter (≈ 3 d) · [P] with WP3 after WP2

| ID | Work item | Est. | Depends | REQs |
|---|---|---|---|---|
| WP4-01 | `_require.py` (`AdapterNotInstalledError`); extra wiring in `pyproject` | 0.5 d | WP0 | 031.3 |
| WP4-02 | `PydanticAIAgent`: `run_stream` with `DeferredToolRequests` injection, deps / deps_factory, run_kwargs | 1 d | WP2-01 | 022.1, 022.4 |
| WP4-03 | Integration with `TestModel`: approval, edit, reject round-trips (the tool runs with the edited args); frontend client tools | 1 d | 02, WP1-11 | 022.2–3, 018 |
| WP4-04 | Contract test TD §8.4 item 2; fixture recorder script (`scripts/record_fixture.py`) | 0.5 d | 03 | TD §8.4, DM §10 |

**Done when:** the adapter tests pass with no network, and the recorded PydanticAI
fixtures are committed.

---

### WP5 — Components and quickstart (≈ 6 d) → **`0.1.0a1` on PyPI**

| ID | Work item | Est. | Depends | REQs |
|---|---|---|---|---|
| WP5-01 | `message_list` (markdown without raw HTML: resolve TD OQ-3), `composer` | 1 d | WP3-06 | 023.2–3, DD-015 |
| WP5-02 | `tool_call_card` + `rx.match` renderer dispatch, `run_status_bar` | 1 d | 01 | 019, 023.4, 023.6 |
| WP5-03 | `approval_dialog` (approve / edit-args JSON / reject; generic interrupt default form and `interrupt_renderers`), `shared_state_panel` | 1.5 d | 01 | 023.5, 023.7 |
| WP5-04 | `agent_chat` composition; accessibility pass (labels, keyboard) | 0.5 d | 02, 03 | 023.1, 023.8–9 |
| WP5-05 | `examples/quickstart` (workspace member) + smoke compile (TD OQ-2) + line-count gate + README-block equality test | 1 d | 04, WP4 | 029 |
| WP5-06 | Release workflow `release.yml`, automatic: a push to `main` whose `__version__` is publishable (not `.dev`) and has no `v<version>` tag yet runs the tests, publishes to PyPI and creates the tag and GitHub Release; a manually pushed `v*` tag publishes too (`uv build` → `uv publish --trusted-publishing always`, `pypi` environment). Publish the pre-release `0.1.0a1` to PyPI. Install it in a fresh `uv venv` and run the quickstart with Claude. | 1 d | 05 | 032.2 |

**Done when:** in a fresh uv project, `uv add "reflex-agentkit[pydantic-ai]==0.1.0a1"`
(the exact pin selects the pre-release from PyPI) followed by the
quickstart works with a real Claude key, in < 5 minutes on a clean
machine (PRD §4.2).

---

### WP6 — LangGraph adapter (≈ 4 d) · [P] with WP5

| ID | Work item | Est. | Depends | REQs |
|---|---|---|---|---|
| WP6-01 | `LangGraphAGUIAgent` subclass (flags, checkpointer check) | 1 d | WP2-01, WP4-01 | 034.1, 034.4 |
| WP6-02 | `request_tool_approval` + `ApprovalDecision`; `_build_command_from_agui_resume` override (native multi-resume, cancelled semantics) | 1 d | 01 | 034.2–3, DD-012 |
| WP6-03 | Integration with a scripted graph + `MemorySaver` + fake chat model: generic interrupt, approval with edits, multi-interrupt, cancel | 1 d | 02 | 034 |
| WP6-04 | Contract test TD §8.4 item 3; `legacy_interrupts` compatibility mode (SHOULD) | 0.5 d | 03 | 034.5 |
| WP6-05 | Report the fastapi-import bug upstream (TD OQ-4) | 0.5 d | — | — |

---

### WP7 — Dojo examples (≈ 5 d)

| ID | Work item | Est. | Depends | REQs |
|---|---|---|---|---|
| WP7-01 | `examples/pydantic_ai_dojo`: agentic chat, backend tool rendering, human-in-the-loop, shared state, tool-based generative UI (multi-page app, 50–200 lines per demo) | 2 d | WP5 | 030.1 |
| WP7-02 | `examples/langgraph_dojo`: the same five demos | 2 d | WP6, WP5 | 030.1 |
| WP7-03 | Model selection by env var (`AGENTKIT_MODEL`, default Claude; documented Ollama option; `test` → TestModel / fake LLM in CI) + smoke compile in CI | 1 d | 01, 02 | 030.2 |

---

### WP8 — Hardening, docs, release (≈ 6 d) → **`0.1.0rc1`, then `v0.1.0`**

| ID | Work item | Est. | Depends | REQs |
|---|---|---|---|---|
| WP8-01 | Security review against TD §6 (forged triggers, payload caps, XSS fixture, header hygiene), with a `/security-review` pass | 1 d | WP5 | Art. 3, TD §6 |
| WP8-02 | Benchmarks (`bench` marker): NFR-01, NFR-04; weekly `deps-latest` CI job | 1 d | WP3 | NFR-01/04, DD-001 |
| WP8-03 | MkDocs Material site: getting started (uv and pip), concepts, API reference, sidecar guide, security model, Ollama guide, troubleshooting (ClassVar, banner) | 1.5 d | WP7 | 033.1, 033.3 |
| WP8-04 | README final: narrative, quickstart (test-locked), feature table, comparison table (Streamlit / CopilotKit / agentstage-ui) | 0.5 d | 03 | 033.1 |
| WP8-05 | `docs/integrations/` upstream drafts (AG-UI integrations entry, PydanticAI page, LangGraph page) | 1 d | 03 | 033.2 |
| WP8-06 | `0.1.0rc1` merged to `main` (published automatically) → fresh-env walkthrough → CHANGELOG `0.1.0` → bump to `0.1.0` and merge to `main` (published and tagged automatically) | 1 d | all | 032.2, PRD §4.1 |

**Done when:** `v0.1.0` is on PyPI, the docs are deployed, and the upstream drafts are
ready to submit.

## 4. Dependency graph and critical path

```
WP0 ──► WP1 ──────────────► WP3 ──► WP5 ──► WP7 ──► WP8
         │                   ▲        ▲       ▲
         └─► WP2 ────────────┤        │       │
                  └─► WP4 ───┴────────┘       │
                  └─► WP6 ────────────────────┘
```

**Critical path:** WP0 → WP1 → WP3 → WP5 → WP7 → WP8 ≈ 43 d of the ≈ 54 d total.
WP2, WP4 and WP6 run alongside it.

## 5. Timeline (indicative, part-time ≈ 5 maintainer-days per 7 calendar days)

| Weeks | WPs | Milestone |
|---|---|---|
| 1 | WP0, start WP1 | CI green on the skeleton |
| 2–4 | WP1, WP2 | `core` complete; coverage ≥ 85 % |
| 5–6 | WP3, WP4 | Streaming and cancel verified; PydanticAI adapter |
| 7 | WP5 | **`0.1.0a1` on PyPI**; quickstart walkthrough |
| 8 | WP6, start WP7 | LangGraph adapter |
| 9 | WP7 | 10 Dojo demos |
| 10–11 | WP8 | **`0.1.0rc1`**, then **`v0.1.0` on PyPI** |

## 6. Risks to the plan

| Risk | Signal | Response |
|---|---|---|
| Reflex in-process testing is harder than expected (OQ-1) | WP3-01 spike exceeds 0.5 d | Test the driver through `StateAccess` only, plus 1–2 AppHarness smoke tests marked `slow` |
| Example compile in CI needs Node/Bun (OQ-2) | WP5-05 | Use the CI `setup-bun` step (Reflex's frontend toolchain), cache it, and run the job only on `examples/**` and `src/**/components/**` changes |
| Upstream release breaks a verified fact | A contract test fails in `deps-latest` | Keep the cap. Open an issue. Fix in a patch release. |
| Reducer misses NFR-01 | WP1 benchmark | DM §5 escape hatch (chunked text), internal only |
| Part-time availability | > 1 week slip | Cut order (WONT for v0.1): REQ-028 retry → REQ-034.5 legacy → REQ-011 reasoning storage → REQ-017 app writes. MUST items never move. |

## 7. Definition of Done (every work package)

1. CI is green on all jobs: lint, typecheck, test matrix, core-no-extras, plus the
   WP-specific jobs.
2. Every task of the WP is checked off in `specs/tasks/agentkit-tasks.md`, and every test
   added cites its REQ.
3. `uv.lock` is updated in the same PR when dependencies changed. `uv sync --locked`
   passes.
4. Docs or CHANGELOG `Unreleased` entries are added for user-visible changes.
5. Any deviation from the specs is reflected in the spec (in-place while unreleased, with
   change-history rows) in the same PR (Art. 9).

---

## Constitution Check

| Article | Compliance |
|---|---|
| Art. 1 | The `core-no-extras` job exists from WP0. Adapters come only after the clients (WP4/WP6). |
| Art. 4–5 | The pure core is built and tested before any Reflex glue (WP1 before WP3). The responsiveness test is in WP3-08. |
| Art. 6–7 | Test-first ordering in WP1. Coverage and strict-typing gates are wired in WP0, before any code. |
| Art. 8 | The quickstart gate and the README-equality test land with the first quickstart (WP5-05). |
| Art. 9 | Spec updates are part of the DoD (§7). Conventional Commits and CHANGELOG from WP0. |
| Stack | uv-only workflow (§1, §1.1–1.2), `uv.lock` committed, `uv publish` with trusted publishing. |
| **Exceptions requested** | None. |

## Change History

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-10-30 | Initial version |
| 1.1 | 2026-10-30 | Analyze fixes: version single source and lazy re-exports (A-01, A-11); gates on core and state (A-04). |
| 1.3 | 2026-10-31 | Maintainer decision: releases are automatic. A push to `main` with a new publishable `__version__` tests, publishes to PyPI and creates the `v<version>` tag and GitHub Release; the `pypi` environment needs no reviewers. The pending-publisher fields are listed in §2. |
| 1.2 | 2026-10-31 | Maintainer decision: no TestPyPI. Pre-releases (`0.1.0a1`, `0.1.0rc1`) and the final release all go to PyPI through the `pypi` environment; only the PyPI trusted publisher and that environment are prerequisites. |
