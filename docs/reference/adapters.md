# Adapters

An adapter turns an agent framework into an [`AGUIAgent`](clients.md#protocols). Each one
is an optional extra; importing an adapter without its extra raises
`AdapterNotInstalledError` (an `ImportError`) that names the `pip install` command.

## PydanticAI

```bash
pip install "reflex-agentkit[pydantic-ai]"
```

```python
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

PydanticAIAgent(
    agent: pydantic_ai.Agent,
    *,
    deps: Any = None,
    deps_factory: Callable[[RunAgentInput], Any | Awaitable[Any]] | None = None,
    **run_kwargs,  # passed to AGUIAdapter.run_stream, e.g. model_settings, usage_limits
)
```

- Runs PydanticAI's AG-UI adapter in process.
- `deps` and `deps_factory` are exclusive (both raise `ConfigurationError`). The factory
  receives the run input, so it can build per-thread dependencies.
- Tools with `requires_approval=True` pause the run for approval with no other setup: the
  adapter adds `DeferredToolRequests` to the run's output type.
- Client tools reach the model as frontend tools.
- Shared state: give the agent `deps_type=StateDeps[MyModel]` and set
  `shared_state_model = MyModel` on the state. A tool updates the state by returning
  `ToolReturn(return_value=..., metadata=[StateSnapshotEvent(snapshot=...)])`. See the
  [PydanticAI Dojo](https://github.com/ecrespo/reflex-agentkit/tree/main/examples/pydantic_ai_dojo).

## LangGraph

```bash
pip install "reflex-agentkit[langgraph]"
```

```python
from reflex_agentkit.adapters.langgraph import (
    ApprovalDecision, LangGraphAGUIAgent, request_tool_approval,
)

LangGraphAGUIAgent(
    graph: CompiledStateGraph,
    *,
    name: str = "agent",
    config: RunnableConfig | None = None,
    legacy_interrupts: bool = False,
)
```

- Builds on the official ag-ui-langgraph integration, with standard interrupts.
- The graph must have a checkpointer; without one, `ConfigurationError`.
- One instance serves every session: each run works on a fresh copy.
- The graph's state reaches `shared_state` without its `messages` and `tools` keys,
  which AG-UI already carries as the conversation and the client tools.
- `interrupt(value)` in the graph becomes `pending_interrupt` with `payload = value`;
  `respond_to_interrupt(answer)` resumes it with `Command(resume=answer)`. Several
  interrupts in one pause are resumed together, each node getting its own answer.
- `legacy_interrupts=True` accepts integrations that only send the older `on_interrupt`
  CUSTOM event; it maps them onto standard interrupts.

### request_tool_approval

```python
request_tool_approval(
    tool_call_id: str, tool_name: str, args: dict[str, Any], *, message: str | None = None
) -> ApprovalDecision


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    args: dict[str, Any]       # the edited arguments if the user edited them
    reason: str | None = None
```

Call it inside a graph node or tool. The UI shows a `pending_approval` tool card instead
of a generic question. A cancelled approval returns
`ApprovalDecision(approved=False, args=<original>, reason="cancelled")`. A cancelled
generic `interrupt()` resumes with `{"__agui_cancelled__": True, "interrupt_id": ...}`.

## Writing your own

Any object with `run(run_input) -> AsyncIterator[BaseEvent]` works. Follow the
[contract](clients.md#protocols), and use the resume payload in
[Human in the loop](../guides/human-in-the-loop.md#the-resume-payload) for approvals.
