# Delta: edited-arguments notice

New criteria take new IDs (REQ-035). No criterion is removed. The open questions in the
proposal were resolved in T-053 (see DD-013 below).

## ADDED

### specs/prd/agentkit-v0.1.md → §7.3 Human-in-the-loop

#### REQ-035 — Tell the model about edited arguments · `MUST`

1. WHEN a tool call approved with `editedArgs` runs through the PydanticAI adapter, THE
   SYSTEM SHALL give the model a tool result made of the tool's own result followed by the
   edited-arguments notice.
2. WHEN a LangGraph node calls `ApprovalDecision.tool_result(result)` for a decision
   approved with edited arguments, THE SYSTEM SHALL return the result followed by the
   edited-arguments notice. For any other decision it SHALL return `result` unchanged.
3. WHEN a tool call is approved without edits, or is rejected, THE SYSTEM SHALL leave the
   tool result unchanged.
4. WHERE `PydanticAIAgent` is constructed with `notify_edited_args=False`, THE SYSTEM SHALL
   leave the tool result unchanged even when the arguments were edited.
5. IF `approve_tool` receives edited arguments equal to the call's current arguments, THEN
   THE SYSTEM SHALL record a plain approval, `{"approved": true}`, without `editedArgs`.
6. THE SYSTEM SHALL log the notice only at DEBUG level.

**The edited-arguments notice (normative, tested):**

```text
Note: the user edited this tool call's arguments before approving it, so the tool ran with: {effective arguments as JSON}. These are the arguments the user wants: do not call the tool again to restore the earlier ones, and do not report the change as an error.
```

- The notice follows the tool's result, separated by a blank line.
- A result that is not a string is serialized to JSON first.
- The notice is part of the tool result, so the tool card in the UI shows it too.
- The last sentence is there because, in the T-056 check, a notice that only stated the
  change still led Claude to describe the result as "not what you asked for". With it,
  Claude explains that the booking was changed before approval, which is accurate.
- It names only the effective arguments (OQ-2). The model's earlier call in the
  history already carries the edited arguments (REQ-013.3), so the server can't
  recover the original ones, and client-sent history isn't trusted anyway.

## MODIFIED

### specs/prd/agentkit-v0.1.md → REQ-013.3

- **Before:** WHEN `approve_tool(call_id, edited_args)` is called with a dict, THE SYSTEM
  SHALL record `{"approved": true, "editedArgs": edited_args}` and show `edited_args` as the
  call's args.
- **After:** the same, except when the dict equals the call's current arguments
  (REQ-035.5).
- **Reason:** an unchanged "edit" must not trigger the notice.

### specs/api/agentkit-python-api-v1.md → §7.1 `PydanticAIAgent`

- New keyword-only constructor argument `notify_edited_args: bool = True` (REQ-035.1,
  REQ-035.4). The adapter adds a per-run capability only when the resumed run has edits,
  so the agent's own capabilities are untouched.

### specs/api/agentkit-python-api-v1.md → §7.6 `ApprovalDecision`

- New field `edited: bool = False`: `True` when the user approved with `editedArgs`.
- New method `tool_result(result: Any) -> Any` (REQ-035.2). The notice is opt-in through
  this method; there is no `LangGraphAGUIAgent` flag, because the node builds the
  `ToolMessage` itself.
- The docs and the Dojo use
  `ToolMessage(decision.tool_result(run_tool(**decision.args)), ...)`.

### specs/technical/agentkit-architecture.md → DD-013 (new decision)

- **PydanticAI:** the adapter maps each resolved `ResumeEntry` with `editedArgs` to its tool
  call ID with `pydantic_ai.ui.ag_ui._interrupt.interrupt_id_to_tool_call_id`. A contract
  test pins this private helper. The adapter then passes a run-level capability whose
  `after_tool_execute` hook appends the notice. `AGUIAdapter.run_stream(capabilities=...)`
  merges it with the agent's own capabilities.
- **LangGraph:** `request_tool_approval` sets `edited`, and `tool_result()` appends the
  notice.
- **Both:** the notice text is one constant in `reflex_agentkit.adapters._edits`, so both
  adapters say the same thing and tests can pin it.

## REMOVED

Nothing.
