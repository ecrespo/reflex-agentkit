# reflex-agentkit

Build and serve AI agents in pure Python with Reflex. AG-UI protocol client, streaming
chat, tool-call cards and human-in-the-loop approval for LangGraph, PydanticAI and any
AG-UI-compatible agent. The production UI layer your agent was missing — no TypeScript,
no Streamlit.

> **Status: pre-alpha, under active development.** Nothing is published on PyPI yet. The
> pure core is implemented and tested; the Reflex state engine, the components and the
> adapters are not. The API below marked *planned* does not exist yet.

## Progress

Work follows the approved spec chain in [`specs/`](specs/) and the task list in
[`specs/tasks/agentkit-tasks.md`](specs/tasks/agentkit-tasks.md).

| Phase | Scope | Status |
|---|---|---|
| WP0 — Foundation | Packaging (uv, hatchling), lint, types, tests, CI | ✅ done |
| WP1 — Pure core | Models, reducer, commands, client tools, `RunInputBuilder`, property tests | ✅ done |
| WP2 — Clients | `AgentClient`/`AGUIAgent` protocols, SSE parser, `HttpAGUIClient`, `InProcessAGUIClient` | 🚧 in progress |
| WP3 — Reflex state engine | `AgentState` mixin, streaming driver, cancellation | ⏳ planned |
| WP4+ — Adapters, components, examples | PydanticAI and LangGraph adapters, chat components, quickstart, docs | ⏳ planned |

## What works today: `reflex_agentkit.core`

The core never imports `reflex`. AG-UI is its only event model, and a pure, total reducer
is the only way agent events change the conversation state.

- **`reduce(state, event)`**: handles all 31 AG-UI 1.0 event types (lifecycle and
  `RUN_FINISHED` outcomes, text, tool calls, shared state via JSON Patch, messages
  snapshots, reasoning, custom events). It never raises: problems become diagnostics.
- **Commands** (`reflex_agentkit.core.commands`): `begin_run`, `apply_approval`
  (optionally with edited arguments), `apply_rejection`, `apply_interrupt_response`,
  `apply_cancel`, `apply_client_tool_result`, `new_thread`, `resume_entries`.
  Human-in-the-loop follows AG-UI standard interrupts and the PydanticAI approval payload.
- **Client tools**: `@client_tool` builds the JSON Schema from type hints. `invoke()`
  runs sync handlers in a worker thread under a timeout and returns failures as tool
  results.
- **`RunInputBuilder`**: turns the conversation into an AG-UI `RunAgentInput` (full
  history, encrypted reasoning, edited tool args, shared state, tools, resume entries).

```python
from reflex_agentkit.core import ConversationState, RunInputBuilder, client_tool
from reflex_agentkit.core.commands import apply_approval, begin_run
from reflex_agentkit.core.models import ReducerConfig
from reflex_agentkit.core.reducer import parse_event, reduce


@client_tool
def pick_date(day: int) -> str:
    """Let the user pick a day of the month."""
    return f"2026-05-{day:02d}"


config = ReducerConfig(client_tool_names=frozenset({"pick_date"}))
conv = begin_run(ConversationState.initial(config), config=config, user_text="book it")
run_input = RunInputBuilder(client_tools=(pick_date,)).build(conv)  # send to the agent

for raw in [  # AG-UI events as they arrive on the wire
    {"type": "RUN_STARTED", "threadId": conv.thread_id, "runId": conv.run_id},
    {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "book_hotel"},
    {"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": '{"city": "Lisbon"}'},
    {"type": "TOOL_CALL_END", "toolCallId": "c1"},
    {"type": "RUN_FINISHED", "threadId": conv.thread_id, "runId": conv.run_id,
     "outcome": {"type": "interrupt",
                 "interrupts": [{"id": "int-c1", "reason": "tool_call", "toolCallId": "c1"}]}},
]:
    event = parse_event(raw)
    conv = reduce(conv, event)

print(conv.run_status)                        # awaiting_input
conv = apply_approval(conv, "c1", {"city": "Porto"})
conv = begin_run(conv, config=config, resume=True)
print(RunInputBuilder().build(conv).resume)   # [ResumeEntry(..., payload={'approved': True, 'editedArgs': {...}})]
```

## Planned usage (not available yet)

```python
import reflex as rx
from reflex_agentkit import AgentState, agent_chat


class ChatState(AgentState, rx.State):
    agent = my_pydantic_ai_agent   # or an HttpAGUIClient pointing at any AG-UI server


def index() -> rx.Component:
    return agent_chat(ChatState)
```

## Development

The workflow is uv only (Python 3.11–3.13).

| Purpose | Command |
|---|---|
| Set up the environment | `uv sync --all-extras` |
| Lint and format check | `uv run ruff check .` · `uv run ruff format --check .` |
| Type check (strict on `core` and `state`) | `uv run mypy` |
| Tests with coverage | `uv run pytest` |
| Coverage gate (≥ 85 % on `core` and `state`) | `uv run python scripts/check_gated_coverage.py` |
| Core isolation check | `uv run python scripts/assert_core_isolated.py` |

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`specs/constitution.md`](specs/constitution.md)
before contributing. The rules: the specs come first, `core` and `state` are written
test-first, and changes use Conventional Commits.

## License

MIT
