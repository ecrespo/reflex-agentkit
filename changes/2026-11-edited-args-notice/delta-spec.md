# Delta: edited-arguments notice

New criteria take new IDs (REQ-035). No criterion is removed.

## ADDED

### specs/prd/agentkit-v0.1.md → §7.3 Human-in-the-loop

#### REQ-035 — Tell the model about edited arguments · `MUST`

1. WHEN a tool call approved with `editedArgs` runs through the PydanticAI adapter, THE
   SYSTEM SHALL give the model a tool result that contains the tool's own result and a
   notice stating that the user edited the arguments before approving, with the original
   arguments and the arguments the tool ran with.
2. WHEN a LangGraph node calls `ApprovalDecision.tool_result(result)` for a decision that
   was approved with edits, THE SYSTEM SHALL return the tool's result with the same notice
   as in REQ-035.1. For a decision without edits it SHALL return `result` unchanged.
3. WHEN a tool call is approved without edits, or is rejected, THE SYSTEM SHALL leave the
   tool result unchanged.
4. WHERE an adapter is constructed with `notify_edited_args=False`, THE SYSTEM SHALL
   leave the tool result unchanged even when the arguments were edited.
5. IF the edited arguments equal the original ones, THEN THE SYSTEM SHALL treat the
   approval as an approval without edits (no notice).
6. THE SYSTEM SHALL log the notice's content only at DEBUG level.

**Notice format (normative, tested):**

```text
Note: the user edited this tool call's arguments before approving it. Original
arguments: {original JSON}. The tool ran with: {effective JSON}.
```

The notice comes after the tool's own result, separated by a blank line. When the result
is not a string, the adapter serializes it the way the framework would have, then
appends the notice.

### specs/api/agentkit-python-api-v1.md → §7.1 `PydanticAIAgent`

- New keyword-only constructor argument `notify_edited_args: bool = True` (REQ-035.1,
  REQ-035.4).

### specs/api/agentkit-python-api-v1.md → §7.6 LangGraph adapter

- `LangGraphAGUIAgent.__init__` gains `notify_edited_args: bool = True`. It is read by
  `request_tool_approval` through the run's config, so `ApprovalDecision.tool_result`
  follows it (REQ-035.4).
- `ApprovalDecision` gains:
  - `original_args: dict[str, Any]`: the arguments the model proposed.
  - `edited: bool`: `True` when the user approved with arguments that differ from
    `original_args` (REQ-035.5).
  - `tool_result(result: Any) -> Any`: REQ-035.2.

## MODIFIED

### specs/prd/agentkit-v0.1.md → REQ-034 (LangGraph adapter)

- **Before:** `request_tool_approval` returns `ApprovalDecision(approved, args, reason)`.
  The node builds the `ToolMessage` from the tool's result.
- **After:** the same, plus `original_args`, `edited` and `tool_result()`. The docs and
  the Dojo show `ToolMessage(decision.tool_result(run_tool(**decision.args)), ...)` as
  the recommended pattern.
- **Reason:** the 2026-10-31 manual run with Claude (see proposal).

### specs/technical/agentkit-architecture.md → §4 (adapters)

- Add a design decision, DD-013, that records where the notice is attached in each
  adapter, the resolution of OQ-1, and why the text is a constant.

## REMOVED

Nothing.
