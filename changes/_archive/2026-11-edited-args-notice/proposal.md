# Proposal: tell the model when the user edited a tool call's arguments

> **Status:** released in `0.2.0` (2026-10-31), folded into `specs/`
> **Base specs:** `specs/prd/agentkit-v0.1.md` (REQ-013, REQ-033, REQ-034),
> `specs/api/agentkit-python-api-v1.md` (§7.4, §7.6), `specs/technical/agentkit-architecture.md`
> **Date:** 2026-10-31 · **Author:** Ernesto Crespo (with Claude)

## Problem

When the user approves a tool call with edited arguments (REQ-013.3), the tool runs with
the edited arguments, but the model is never told that they changed. All it sees is its
own call with the original arguments, followed by a result that does not match them.

The manual run with Claude (`claude-sonnet-5-5`, 2026-10-31) showed what happens next.
The model asked to book Lisbon for 2 nights; the user changed that to Porto for 3 nights;
the tool returned "Booked 3 nights in Porto."

- **LangGraph:** the model told the user "The booking came back wrong. I asked for 2
  nights in Lisbon, but the system confirmed 3 nights in Porto."
- **PydanticAI:** the model called the tool again with the original arguments (Lisbon,
  2 nights). That second call stopped at `pending_approval`, so the approval gate held,
  but the user had to reject it by hand.

With Ollama `qwen3:8b` the same flow happened to pass, so the problem is model-dependent.
Stronger models check results against their calls, so they are the ones most likely to
"correct" the user. The library behaves as specified; the specification leaves the model
uninformed.

## Scope

**In scope**

- When a call is approved with edited arguments, the model receives an explicit notice in
  the tool's result: that the user changed the arguments, and the arguments the tool
  actually ran with.
- Both adapters: the PydanticAI adapter (REQ-033) and the LangGraph adapter (REQ-034).
- An opt-out, for apps whose tools already report their effective arguments.
- Documentation (HITL guide, adapters reference) and the Dojo `human_in_the_loop` demos.

**Out of scope**

- Approvals without edits and rejections. Rejections already carry `reason`.
- Generic interrupts (REQ-014): their payloads are app-defined.
- The UI: the approval card already shows the edited arguments (REQ-013.3).
- `HttpAGUIClient` against third-party AG-UI servers: what the server tells its model is
  the server's business. The sidecar case is covered because the sidecar runs the
  adapters.

## Impact

- **Observable behavior:** the tool result the model sees changes when arguments were
  edited, so the model's replies change. That is the purpose of the change.
- **API:** additive only. There is a new constructor option on both adapters, and
  `ApprovalDecision` gains read-only fields. Nothing is removed or renamed, so this is a
  minor release (0.2.0).
- **Compatibility:** apps that build their own `ToolMessage` in LangGraph keep working.
  They get the notice only if they use the new helper (see the delta, MODIFIED REQ-034).
- **Risks:**
  - Prompt-visible text is part of the contract, so it gets tests that pin its shape.
  - PydanticAI may not expose a supported hook to annotate the result of an approved
    deferred tool (open question OQ-1 below). If it doesn't, the fallback is to wrap the
    tool's return value inside the adapter. That must be verified against the pinned
    `pydantic-ai-slim` before implementation.

## Open questions (resolve before implementation)

- **OQ-1.** How do we attach the notice to an approved deferred tool's result in
  `pydantic-ai-slim` 2.64? Candidates: `ToolApproved(override_args=...)` plus a result
  wrapper in the adapter, a `ToolReturn` with extra content, or a supported hook if one
  exists. Verify with Context7 / the source; do not assume.
- **OQ-2.** Should the notice carry the original arguments as well as the effective ones?
  Proposed: yes. A diff is easier for the model to reason about, and both are already in
  the conversation.
- **OQ-3.** What format should the notice take? Proposed: one short English sentence
  followed by JSON. The sentence is a constant in the adapter, not configurable, to keep
  the behavior testable.

## Constitution check

- **Art. 1 (core has no extras):** the change lives in the adapters. `core` is untouched.
- **Secrets out of State:** no new state vars. The notice goes to the model, not to the
  browser.
- **No telemetry, no extra network calls:** none are added.
- **Logging:** the notice contains user content (arguments), so it is logged at DEBUG
  only.
- **Test-first:** every new criterion gets a `test_REQ_035_k_...` test before the code.
- **Spec drift:** the delta is folded into `specs/` in the PR that implements it.
