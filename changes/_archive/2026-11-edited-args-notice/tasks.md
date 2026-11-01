# Tasks: edited-arguments notice

> Status: done 2026-10-31; folded into `specs/` and archived.
> Rules: same as `specs/tasks/agentkit-tasks.md` (test-first, `test_REQ_035_k_...`, gates
> green, README and CHANGELOG updated). Folding the delta into `specs/` is part of the
> last task.

- [x] **T-053** Resolve OQ-1 to OQ-3. Verify against the pinned `pydantic-ai-slim` (Context7
  plus source) how to annotate an approved deferred tool's result. Record the answer as
  DD-016 in the TD (change-history row). Refs: REQ-035.1.
- [x] **T-054** PydanticAI adapter: `notify_edited_args` plus the notice. Tests first: notice
  present when edited (REQ-035.1), absent without edits, on rejection, when the flag is
  off, or when the edits equal the original args (REQ-035.3–5), and DEBUG-only logging
  (REQ-035.6). Use the PydanticAI `TestModel` / `FunctionModel`, no network.
- [x] **T-055** LangGraph adapter: `ApprovalDecision.original_args`, `edited`,
  `tool_result()`, and `notify_edited_args` on `LangGraphAGUIAgent`. Tests first
  (REQ-035.2–6).
- [x] **T-056** Dojo `human_in_the_loop` demos (both), the HITL guide and the adapters
  reference use the new pattern. Re-run the manual check with Claude and with Ollama:
  after approving Lisbon → Porto, the model must not call the tool again or treat the
  change as an error. Mentioning that the user changed the booking is fine, and accurate.
- [x] **T-057** Fold the delta into `specs/` (PRD v1.4 REQ-035, API v1.7 §7.5 and §7.6, TD
  v1.17 DD-016), add a CHANGELOG entry under `[Unreleased]` (the version bump is a
  separate release decision), and archive this folder to `changes/_archive/`.

## Notes

- T-053: `after_tool_execute` on a run-level capability works on 2.64 (spike plus the
  contract tests). OQ-2: the notice names only the effective arguments. DD-016 has the
  details.
- T-056: Claude (`claude-sonnet-5-5`, two runs) no longer calls the tool again, and
  explains that the booking was changed before approval. Ollama `qwen3:8b` confirms the
  edited booking. The notice's last sentence was added after the first Claude check.
