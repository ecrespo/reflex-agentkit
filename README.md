# reflex-agentkit

Build and serve AI agents in pure Python with Reflex. AG-UI protocol client, streaming
chat, tool-call cards and human-in-the-loop approval for LangGraph, PydanticAI and any
AG-UI-compatible agent. The production UI layer your agent was missing — no TypeScript,
no Streamlit.

> **Status: pre-alpha, under active development.** Nothing is published on PyPI yet; the
> first pre-release (`0.1.0a1`, on PyPI) is built and waiting for the release setup.
> The pure core, the agent clients, the Reflex state engine (`AgentState`), the chat
> components and both adapters (PydanticAI and LangGraph) are implemented and tested.

## Quickstart

A streaming chat with a PydanticAI travel agent, one tool call shown as a card and one
tool that waits for your approval. This is the whole app
([`examples/quickstart/`](examples/quickstart/)):

<!-- quickstart:start -->
```python
from typing import ClassVar

import reflex as rx
from pydantic_ai import Agent

from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

travel_agent = Agent(
    "anthropic:claude-sonnet-5-5",
    instructions="You are a helpful travel assistant.",
)


@travel_agent.tool_plain
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It is sunny and 22 °C in {city}."


@travel_agent.tool_plain(requires_approval=True)
def book_hotel(city: str, nights: int) -> str:
    """Book a hotel room. Requires human approval."""
    return f"Booked {nights} nights in {city}."


class ChatState(AgentState, rx.State):
    agent: ClassVar = PydanticAIAgent(travel_agent)


def index() -> rx.Component:
    return agent_chat(ChatState)


app = rx.App()
app.add_page(index)
```
<!-- quickstart:end -->

Run it from a clone of this repo:

```bash
uv sync --all-extras
cd examples/quickstart
ANTHROPIC_API_KEY=sk-ant-... uv run --package quickstart reflex run
```

Ask it to plan a trip: it shows the `get_weather` call and opens the approval dialog
before `book_hotel` runs. The agentkit components are built on Radix Themes, so the
example's `rxconfig.py` adds `rx.plugins.RadixThemesPlugin()`.

To use a local model instead of Claude, swap the model line for an Ollama model through
PydanticAI's Ollama provider, for example `Agent("ollama:qwen3", ...)` with
`OLLAMA_BASE_URL=http://localhost:11434/v1`.

The components are in `reflex_agentkit.components`: `agent_chat` composes
`message_list`, `tool_call_card`, `composer`, `run_status_bar`, `approval_dialog` and,
with `show_shared_state=True`, `shared_state_panel`. Custom renderers for a tool
(`tool_renderers={"get_weather": ...}`) or an interrupt reason
(`interrupt_renderers={...}`) replace the default card body or form. Every control has
an accessible label.

## Progress

Work follows the approved spec chain in [`specs/`](specs/) and the task list in
[`specs/tasks/agentkit-tasks.md`](specs/tasks/agentkit-tasks.md).

| Phase | Scope | Status |
|---|---|---|
| WP0 — Foundation | Packaging (uv, hatchling), lint, types, tests, CI | ✅ done |
| WP1 — Pure core | Models, reducer, commands, client tools, `RunInputBuilder`, property tests | ✅ done |
| WP2 — Clients | `AgentClient`/`AGUIAgent` protocols, SSE parser, `HttpAGUIClient`, `InProcessAGUIClient` | ✅ done |
| WP3 — Reflex state engine | `AgentState` mixin, streaming driver, cancellation, client-tool rounds | ✅ done |
| WP4 — PydanticAI adapter | `PydanticAIAgent`: a PydanticAI agent as an `AGUIAgent`, tool approvals, client tools | ✅ done |
| WP5 — Components and quickstart | `agent_chat` and its parts, quickstart example, release workflow | ✅ done (PyPI publish pending the release setup) |
| WP6 — LangGraph adapter | `LangGraphAGUIAgent`, `request_tool_approval`, legacy interrupts | ✅ done |
| WP7 — Dojo examples | The five AG-UI Dojo demos for PydanticAI and LangGraph | ✅ done |
| WP8 — Hardening, docs, release | Documentation site, `0.1.0` on PyPI | 🚧 next |

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
- **Agent clients**: `HttpAGUIClient` talks to any AG-UI server over HTTP + SSE.
  `InProcessAGUIClient` runs an agent object (anything with
  `run(run_input) -> AsyncIterator[event]`) in the same event loop. Both yield validated
  events, skip invalid ones with a log record, raise typed `AgentHTTPError` /
  `AgentStreamError` on transport failures, and close the upstream when the consumer is
  cancelled. Headers such as API keys are never logged or put in error messages.

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

Streaming a run from an AG-UI server:

```python
import asyncio
import os

from reflex_agentkit import HttpAGUIClient
from reflex_agentkit.core import ConversationState, RunInputBuilder
from reflex_agentkit.core.commands import begin_run
from reflex_agentkit.core.models import ReducerConfig
from reflex_agentkit.core.reducer import reduce


async def main() -> None:
    client = HttpAGUIClient(
        "http://localhost:8000/agent",
        headers=lambda: {"Authorization": f"Bearer {os.environ['AGENT_TOKEN']}"},
    )
    config = ReducerConfig()
    conv = begin_run(ConversationState.initial(config), config=config, user_text="Hello!")
    try:
        async for event in client.stream(RunInputBuilder().build(conv)):
            conv = reduce(conv, event)
    finally:
        await client.aclose()
    print(conv.run_status, conv.messages[-1].content)


asyncio.run(main())
```

## `AgentState` with your own UI

`AgentState` is a Reflex state mixin that holds a conversation with an AG-UI agent. Its
configuration is class-level (`ClassVar`), so the agent, its client and any API keys
never become state vars sent to the browser. `agent_chat` is optional: this example
builds its own UI from plain Reflex components:

```python
from typing import ClassVar

import reflex as rx

from reflex_agentkit import AgentState, HttpAGUIClient


class ChatState(AgentState, rx.State):
    agent: ClassVar = HttpAGUIClient("http://localhost:8000/agent")
    draft: str = ""

    @rx.event
    def set_draft(self, value: str) -> None:
        self.draft = value

    @rx.event
    def submit(self):
        text, self.draft = self.draft, ""
        return ChatState.send_message(text)


def index() -> rx.Component:
    return rx.vstack(
        rx.foreach(ChatState.messages, lambda m: rx.text(m.role, ": ", m.content)),
        rx.cond(ChatState.error != "", rx.callout(ChatState.error, color_scheme="red")),
        rx.hstack(
            rx.input(value=ChatState.draft, on_change=ChatState.set_draft),
            rx.button("Send", on_click=ChatState.submit, disabled=~ChatState.can_send),
            rx.button("Stop", on_click=ChatState.cancel_run, disabled=~ChatState.is_running),
        ),
    )


app = rx.App()
app.add_page(index)
```

- **Streaming**: the reply streams in a background task; state pushes are batched (at most
  one per `flush_interval_ms`, default 50 ms).
- **Handlers**: `send_message`, `cancel_run` (stops within 1 s, also when another backend
  worker handles the click), `approve_tool` / `reject_tool` (with edited arguments),
  `respond_to_interrupt`, `new_thread`, `set_shared_state` / `patch_shared_state`,
  `retry_run`. Calls that are not allowed in the current status are no-ops, so they are
  safe to call from the browser at any time.
- **Client tools**: `client_tools: ClassVar = (my_tool,)` runs `@client_tool` handlers on
  the server and starts the follow-up run, with optional approval
  (`@client_tool(requires_approval=True)`).
- **Hooks**: override `create_client` (for example, per-user auth headers),
  `prepare_run_input`, `on_custom_event` or `on_run_end`.

## What works today: the PydanticAI adapter

Install the extra (`reflex-agentkit[pydantic-ai]`) and wrap the agent. Tools declared with
`requires_approval=True` pause the run for `approve_tool` / `reject_tool` with no extra
configuration; edited arguments reach the tool.

```python
from typing import ClassVar

import reflex as rx
from pydantic_ai import Agent

from reflex_agentkit import AgentState
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

agent = Agent("anthropic:claude-sonnet-5-5", instructions="You book hotels.")


@agent.tool_plain(requires_approval=True)
def book_hotel(city: str) -> str:
    """Book a hotel in a city."""
    return f"Booked a hotel in {city}."


class ChatState(AgentState, rx.State):
    agent: ClassVar = PydanticAIAgent(agent)
```

## What works today: the LangGraph adapter

Install the extra (`reflex-agentkit[langgraph]`) and wrap a compiled graph that has a
checkpointer. `interrupt(value)` in the graph shows up as `pending_interrupt` and is
answered with `respond_to_interrupt`. `request_tool_approval` pauses for a tool call and
shows the approval dialog; it returns the decision, with edited arguments when the user
changed them. In this sketch, `call_model` stands for your own chat-model node:

```python
from typing import Any, ClassVar

import reflex as rx
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph

from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent, request_tool_approval


def tools(state: MessagesState) -> dict[str, Any]:
    last = state["messages"][-1]
    assert isinstance(last, AIMessage)
    call = last.tool_calls[0]
    decision = request_tool_approval(str(call["id"]), call["name"], call["args"])
    content = f"Booked {decision.args['city']}" if decision.approved else "Not booked"
    return {"messages": [ToolMessage(content=content, tool_call_id=call["id"])]}


def route_to_tools_or_end(state: MessagesState) -> str:
    return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END


builder = StateGraph(MessagesState)
builder.add_node("model", call_model)  # your chat-model node, e.g. ChatAnthropic + bind_tools
builder.add_node("tools", tools)
builder.add_edge(START, "model")
builder.add_conditional_edges("model", route_to_tools_or_end, ["tools", END])
builder.add_edge("tools", "model")


class ChatState(AgentState, rx.State):
    agent: ClassVar = LangGraphAGUIAgent(builder.compile(checkpointer=InMemorySaver()))


def index() -> rx.Component:
    return agent_chat(ChatState)
```

- One agent instance serves every session; each run works on a fresh copy.
- Several interrupts at once are answered one at a time in the UI and resumed together,
  each node receiving its own answer.
- Cancelling while paused resumes the next run with
  `ApprovalDecision(approved=False, reason="cancelled")` for an approval, or the
  `{"__agui_cancelled__": True}` value for a generic interrupt.
- `legacy_interrupts=True` supports integrations that only send the older `on_interrupt`
  event.

## Examples

| Example | What it is |
|---|---|
| [`examples/quickstart/`](examples/quickstart/) | The quickstart above: a chat with a PydanticAI agent in 23 lines |
| [`examples/pydantic_ai_dojo/`](examples/pydantic_ai_dojo/) | The five AG-UI Dojo demos with PydanticAI |
| [`examples/langgraph_dojo/`](examples/langgraph_dojo/) | The same five demos with LangGraph graphs |

The Dojo demos are agentic chat, backend tool rendering, human in the loop (approve, edit
or reject a tool call; answer a question), shared state and tool-based generative UI.
They use Claude by default; `AGENTKIT_MODEL=ollama:<model>` switches to a local Ollama
model, and `AGENTKIT_MODEL=test` to an offline model (see
[`examples/_shared`](examples/_shared/README.md)).

## Development

The workflow is uv only (Python 3.11–3.13).

| Purpose | Command |
|---|---|
| Set up the environment | `uv sync --all-extras --all-packages` |
| Lint and format check | `uv run ruff check .` · `uv run ruff format --check .` |
| Type check (strict on `core` and `state`) | `uv run mypy` |
| Tests with coverage | `uv run pytest` |
| Coverage gate (≥ 85 % on `core` and `state`) | `uv run python scripts/check_gated_coverage.py` |
| Core isolation check | `uv run python scripts/assert_core_isolated.py` |
| Quickstart smoke (offline) | `uv run pytest tests/smoke` |

Releases are automatic: merging a new version into `main` publishes it to PyPI (see
[`CONTRIBUTING.md`](CONTRIBUTING.md#releases)).

Read [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`specs/constitution.md`](specs/constitution.md)
before contributing. The rules: the specs come first, `core` and `state` are written
test-first, and changes use Conventional Commits.

## License

MIT
