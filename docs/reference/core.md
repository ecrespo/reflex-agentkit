# Core types and reducer

`reflex_agentkit.core` has no Reflex dependency: it is the pure, testable part of the
library, usable on its own (for example, in a different UI or in tests).

## Value types

Frozen and JSON-serializable.

### ChatMessage

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | AG-UI `messageId` |
| `role` | `"user" \| "assistant" \| "tool"` | AG-UI role names |
| `content` | `str` | Grows while streaming |
| `streaming` | `bool` | True between start and end |
| `tool_call_ids` | `list[str]` | Assistant messages: the calls it issued |
| `tool_call_id` | `str \| None` | Tool messages: the call this result belongs to |
| `reasoning` | `str` | Reasoning text of the turn (not rendered by the components) |
| `is_error` | `bool` | Tool messages: the tool failed or was rejected |

### ToolCall

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | AG-UI `toolCallId` |
| `name` | `str` | The tool name |
| `args_text` | `str` | The raw argument text, as streamed |
| `args` | `dict \| None` | Parsed arguments; the edited ones after an approval with edits |
| `status` | `ToolCallStatus` | `streaming`, `pending_approval`, `running`, `done`, `rejected`, `error` |
| `result` | `str \| None` | The result, or an error or rejection text |
| `parent_message_id` | `str \| None` | The assistant message that issued it |
| `interrupt_id` | `str \| None` | Set while (or after) it waits for approval |
| `is_client_tool` | `bool` | Handled by a client tool |

### PendingInterrupt

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | AG-UI `Interrupt.id` |
| `reason` | `str` | Picks the interrupt renderer |
| `message` | `str` | The prompt for the user |
| `payload` | `Any` | Agent data (LangGraph: the `interrupt(value)` argument) |
| `response_schema` | `dict \| None` | JSON Schema for the answer |
| `queue_position`, `queue_size` | `int` | Position among the questions of this pause |

### Others

- `CustomEventRecord`: `name`, `value`, `run_id`.
- `RunStatus`, `ToolCallStatus` and `ErrorCode` are `StrEnum`s, so
  `run_status == "running"` and `run_status == RunStatus.RUNNING` both hold.

## The reducer

```python
from reflex_agentkit.core import ConversationState, reduce
from reflex_agentkit.core.reducer import parse_event

event = parse_event(raw_json_dict)   # an ag_ui.core event, or a Diagnostic
conv = reduce(conv, event)
```

- `reduce` is pure, deterministic and total: it never mutates its input and never
  raises for a validated event. Problems become `Diagnostic`s on the result, which
  `AgentState` logs and clears.
- `parse_event` validates a wire event; unknown types and invalid events return a
  `Diagnostic` instead of raising.
- `ConversationState` holds everything the reducer owns. `AgentState` keeps it in a
  backend-only var and projects it onto the public vars at each push.

The transitions that are not events are pure functions in
`reflex_agentkit.core.commands`: `begin_run`, `apply_approval`, `apply_rejection`,
`apply_interrupt_response`, `apply_cancel`, `apply_client_tool_result`, `new_thread` and
`resume_entries`. `RunInputBuilder` turns a conversation into the `RunAgentInput` of the
next run.

```python
from reflex_agentkit.core import ConversationState, RunInputBuilder
from reflex_agentkit.core.commands import apply_approval, begin_run
from reflex_agentkit.core.models import ReducerConfig

config = ReducerConfig()
conv = begin_run(ConversationState.initial(config), config=config, user_text="book it")
run_input = RunInputBuilder().build(conv)  # send this to the agent
```
