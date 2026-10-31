# Analyze — reflex-agentkit v0.1 · 2026-10-30

> **Scope:** Constitution v1.0, PRD v1.1, API v1.1, TD v1.0, Data Model v1.0, Plan v1.0,
> Tasks v1.0.
> **Method:** read-only cross-artifact review (checklist `11-CHECKLIST-ANALYZE`).
> - **Mechanical checks:** REQ/criterion coverage, ghost IDs, dependency cycles, enum
>   parity.
> - **Manual review:** the 7 categories.
> - **One read-only spike:** PydanticAI frontend-tool termination (A-18).
>
> **No artifact was modified by this analysis.**
>
> **Status (2026-10-30): APPLIED.** A-01…A-16 applied, A-17 accepted (noted in API §4.6), A-18 added
> to TD §8.4 and T-035. Resulting versions: Constitution v1.1, PRD v1.2, API v1.2, TD v1.1,
> DM v1.1, Plan v1.1, Tasks v1.1. Each document has a change-history row.

## Mechanical results

| Check | Result |
|---|---|
| REQs defined | 34 (28 MUST, 5 SHOULD, 1 COULD), 131 numbered criteria |
| Ghost REQs (cited, not defined) | none |
| Criteria not cited by any task's REQ line | REQ-003.2, REQ-026.1 → A-13 |
| Task dependency cycles | none (52 tasks) |
| Forward dependencies (depends on a later-listed task) | T-016 → T-017 → A-14 |
| `ErrorCode` parity API §9.2 ↔ DM §6 | identical (10 codes) |
| Orphan tasks | none (T-024 → TD OQ-1; T-046 → REQ-030.2) |

## Findings

| # | Severity | Category | Finding | Artifacts | Suggestion |
|---|---|---|---|---|---|
| A-01 | HIGH | Constitution / executability | API §1 promises that `reflex_agentkit.core` never imports `reflex`, and T-003's `core-no-extras` job asserts it. But API §3 makes the top-level `reflex_agentkit/__init__.py` re-export `AgentState` and the components. Python runs the parent package's `__init__` before any submodule, so `import reflex_agentkit.core` would import `reflex` as soon as T-039 adds the re-exports. The check passes in WP0 and breaks in WP5, and an agent would "fix" it by inventing something. | API §1, §3; TD §5.1; T-001, T-003, T-039 | Top-level `__init__.py` uses **lazy re-exports (PEP 562 module `__getattr__`)** for the names that need Reflex; `__all__` is unchanged. Add this to TD §5.1, T-001 and T-039. T-039 Done adds a test: `import reflex_agentkit.core` leaves `"reflex"` out of `sys.modules`. |
| A-02 | HIGH | Consistency | PRD REQ-004.1 says `RUN_FINISHED` (no interrupt) → `idle`, but TD Flow B / DD-009 keeps `running` through client-tool rounds. As written, the reducer sets `idle`, the UI flickers, and `can_send` briefly opens mid-turn (a race that lets the user send a message between rounds). | PRD 004.1, 018.2; TD Flow B; DM §7.1 | Amend REQ-004.1 to: "…without an interrupt outcome **and with no client-side tool call awaiting execution**…". Add a reducer rule in DM §7.1: `RUN_FINISHED(success)` with `is_client_tool` calls in `running` keeps `running`. The verified `RunFinishedSuccessOutcome.pending_tool_call_ids` (A-18), when present, is authoritative for which calls await results. |
| A-03 | HIGH | Ambiguity / coverage | PRD REQ-022.4 (configuration error when `output_type` cannot express deferred requests) cannot be tested after Q-3: API v1.1 says it is "satisfied by construction". T-033 lists it, but its Done tests only REQ-022.1. This is a MUST with no observable outcome (EARS theater). | PRD 022.4; API §7.5; T-033 | Rewrite REQ-022.4 as: "WHERE the wrapped agent has approval-required tools and its `output_type` lacks `DeferredToolRequests`, THE SYSTEM SHALL inject it at run time so that the run ends with an interrupt outcome." Add `test_REQ_022_4_injects_deferred_requests` to T-033 Done. |
| A-04 | HIGH | Constitution | Art. 6 names "the reducer, the clients **and `AgentState`**" as test-first core code, but the coverage gate (≥ 85 %) and Art. 7's `mypy --strict` apply only to `reflex_agentkit.core`. The API and TD placed `AgentState` and `RunDriver` (the most race-prone code) in `reflex_agentkit.state`, which is outside both gates. | Constitution Art. 6–7; API §1; TD §5.1; T-002 | Constitution **v1.1 clarification**: the gates apply to `reflex_agentkit.core` **and** `reflex_agentkit.state`. Update T-002 (mypy override, coverage script) and Plan WP0-02. This is the cheap direction; leaving the gates as they are leaves the riskiest module unguarded. |
| A-05 | HIGH | Data / consistency | INV-4 (`awaiting_input` ⇔ open interrupts with an unanswered one) is violated by cancel-while-paused as specified. `apply_cancel` sets `cancelled`, but DM never says that `interrupts` and `answers` are cleared. The property test (T-018) would fail, or the agent would weaken the invariant. | DM §3.10, §4; PRD 015.2–3; T-015 | DM §3.10: `apply_cancel` (paused) **moves the non-local interrupt IDs to `abandoned_interrupt_ids` and clears `interrupts` and `answers`**. Local (client-tool) approvals are dropped. Add the corresponding rule to T-015. |
| A-06 | HIGH | Unhappy paths / consistency | Error mapping for an in-process agent exception: API §9.2 and TD Flow E say `AGENT_CONNECT_ERROR`, but T-023 maps it to `AgentStreamError`, which the driver maps to `AGENT_STREAM_ERROR`. The name `AGENT_CONNECT_ERROR` also misdescribes "the agent raised". | API §9.1–9.2; TD Flow E; T-023, T-026 | Since this is unreleased: rename the code to **`AGENT_EXCEPTION`** (an in-process agent raised, or `create_client()` failed). T-023 raises `AgentStreamError(reason="agent_raised")`, and the driver maps it by `reason`. HTTP connect failures stay `AGENT_STREAM_ERROR`. Update API §9.2, DM §6, TD Flow E, T-023 and T-026. |
| A-07 | MEDIUM | Data | INV-8 is bidirectional, but `send_message` while `run_status == error` with too-long text sets `MESSAGE_TOO_LONG` while the status stays `error`. That breaks the "status error ⇒ run-level code" direction. | DM §4; API §4.3 | Make INV-8 one-directional: "a run-level `error_code` ⇒ `run_status == error`". Non-fatal codes overwrite `error_code` without changing the status. |
| A-08 | MEDIUM | Coverage | `ChatMessage.is_error` exists in DM §3.1 (a public type, and DM §8 says public fields are API) but is missing from API §5.1. | DM §3.1; API §5.1 | Add `is_error: bool` to API §5.1 (tool messages: the tool failed or was rejected). |
| A-09 | MEDIUM | Consistency | API §4.5's run-status diagram has no edge for `RUN_FINISHED(outcome=cancelled)` → `cancelled`, although API §8.3 (v1.1) and DM §7.1 define it. | API §4.5, §8.3 | Add the edge `running ─ RUN_FINISHED(outcome=cancelled) ▶ cancelled`. |
| A-10 | MEDIUM | Terminology | The PRD says "`human` message" (REQ-001.1, §7 conventions, US-001), while the API, DM and TD use role `user` (API §5.1 explains the mapping, but the PRD itself still names a role value that does not exist). | PRD §7.1; API §5.1 | Change the PRD wording to "a `user` message (the human's turn)". Glossary: add **user message**. |
| A-11 | MEDIUM | Executability | The source of `__version__` contradicts itself. API §3 says "read from package metadata". Plan §1.2 says hatch reads it from the literal in `__init__.py` **and** that `__version__` reads `importlib.metadata`. | API §3; Plan §1.2; T-001 | Single source: the literal `__version__ = "…"` in `src/reflex_agentkit/__init__.py`, read by `[tool.hatch.version]`. Drop the `importlib.metadata` statement. API §3: "a `str` literal, the single source of the package version". |
| A-12 | MEDIUM | Unhappy paths | `retry_run` (COULD) truncates after the last user message, dropping tool results. Non-approval backend tools with side effects can then run **again** (duplicate external effects). There is no idempotency statement. | PRD 028; API §4.3 | Document in API §4.3 and the docs: "retry may re-execute backend tools; tools with external side effects should use `requires_approval=True` or be idempotent." Approval-required tools naturally ask again. No code change. |
| A-13 | MEDIUM | Coverage | REQ-003.2 (two concurrent clients get only their own events) and REQ-026.1 (disconnect → the run continues) are not cited on any task's **REQ** line (the matrix mentions REQ-026 informally). | PRD 003.2, 026.1; tasks | T-031: add `test_REQ_003_2_concurrent_clients_isolated` (two tokens streaming at once). T-004: cite REQ-026.1 on the Reflex-disconnect contract test. |
| A-14 | LOW | Executability | T-016 depends on T-017, which is listed after it. This contradicts the "order = execution order" convention. | tasks | Swap T-016 and T-017 in the file order (keep the IDs, or renumber before the first commit). |
| A-15 | LOW | Executability | T-051 is `[P]`, but T-050's `Files: docs/**` includes T-051's `docs/integrations/**`. | tasks | Narrow T-050 to `docs/**` excluding `docs/integrations/`. |
| A-16 | LOW | Constitution (Art. 7) | T-002 configures mypy `ignore_missing_imports` for `jsonpatch`, and DD-007 *also* uses an inline `# type: ignore[import-untyped]`. One of them is redundant, and the global setting hides the reason that Art. 7 requires inline. | T-002; TD DD-007 | Keep only the inline ignore with its reason (DD-007). Remove `ignore_missing_imports` from T-002. |
| A-17 | LOW | UX consistency | `approve_tool` sets the call to `running` immediately, even when other interrupts are still unanswered and no run has started yet, so the card shows "running" before anything runs. | PRD 013.2; API §4.6 | Accept it as is (simple, and the resume follows the last answer), or set `running` only when the resume run starts. Recommend accepting and noting it in API §4.6. |
| A-18 | INFO (verified) | Unhappy paths | Spike (pydantic-ai-slim 2.64.0, `TestModel`): a call to a **frontend/client tool** ends with `RUN_FINISHED(outcome=success)`, **not** an interrupt, with or without the `DeferredToolRequests` injection. `RunFinishedSuccessOutcome` carries `pending_tool_call_ids` (None in this run). This confirms TD Flow B, so the reducer will not misread client tools as approvals. It also feeds A-02. | TD Flow B, §8.4 | Add it to the contract tests (T-035, TD §8.4 item 2). |

### Categories with no findings

- **Ambiguity:** every other EARS criterion names an observable outcome, and the limits
  carry values and units (32,000 chars; 50 ms; 1 s; 60 s; 1 MiB; 64 KiB; 3600 s).
- **Data:** no money or financial data. IDs have a defined format (DM R-7). Every hot
  path has its structure (DM §5). Migrations are covered by the tolerant pickle (DM §8).
- **Executability:** every Done is a command or a concrete observation. The first batch
  is identified (T-001…T-005).

## Verdict

**FIX HIGH FINDINGS FIRST.** There are no critical findings. There are six HIGH
findings (A-01…A-06): each one is a gap that an implementing agent would fill by
invention. All of them are spec edits only (no redesign) and touch unreleased documents.

**Recommendation:**
- Apply A-01…A-13 in one spec-maintenance pass (in place, with change-history rows):
  Constitution v1.1, PRD v1.2, API v1.2, TD v1.1, DM v1.1, Plan v1.1, Tasks v1.1.
- Apply A-14…A-16 at the same time (trivial).
- Accept A-17 as noted.
- Then start T-001…T-005.

The only findings that affect the **first batch** are A-01 (T-001's skeleton must
create the lazy `__init__`), A-04 (T-002's gate scope), A-11 (T-001's version source)
and A-16 (T-002).

*The Analyze does not approve anything: it presents findings. Approval is human.*
