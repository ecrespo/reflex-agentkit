# Tasks: edited-arguments notice

> Status: approved 2026-10-31, in implementation.
> Rules: same as `specs/tasks/agentkit-tasks.md` (test-first, `test_REQ_035_k_...`, gates
> green, README and CHANGELOG updated). Folding the delta into `specs/` is part of the
> last task.

- [ ] **T-053** Resolve OQ-1 to OQ-3. Verify against the pinned `pydantic-ai-slim` (Context7
  plus source) how to annotate an approved deferred tool's result. Record the answer as
  DD-013 in the TD (change-history row). Refs: REQ-035.1.
- [ ] **T-054** PydanticAI adapter: `notify_edited_args` plus the notice. Tests first: notice
  present when edited (REQ-035.1), absent without edits, on rejection, when the flag is
  off, or when the edits equal the original args (REQ-035.3–5), and DEBUG-only logging
  (REQ-035.6). Use the PydanticAI `TestModel` / `FunctionModel`, no network.
- [ ] **T-055** LangGraph adapter: `ApprovalDecision.original_args`, `edited`,
  `tool_result()`, and `notify_edited_args` on `LangGraphAGUIAgent`. Tests first
  (REQ-035.2–6).
- [ ] **T-056** Dojo `human_in_the_loop` demos (both), the HITL guide and the adapters
  reference use the new pattern. Re-run the manual check with Claude and with Ollama:
  after approving Lisbon → Porto, the model must neither call the tool again nor report
  a mismatch.
- [ ] **T-057** Fold the delta into `specs/` (PRD REQ-035, API §7.1 and §7.6, TD DD-013),
  CHANGELOG `[0.2.0]` entry, and archive this folder to `changes/_archive/`.
