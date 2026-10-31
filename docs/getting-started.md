# Getting started

reflex-agentkit needs Python 3.11, 3.12 or 3.13. The package is `reflex-agentkit`; the
import is `reflex_agentkit`. The agent frameworks are optional extras:

| Extra | Installs | For |
|---|---|---|
| *(none)* | Reflex, `ag-ui-protocol`, `httpx` | AG-UI servers over HTTP (`HttpAGUIClient`), your own `AGUIAgent` |
| `pydantic-ai` | `pydantic-ai-slim[ag-ui,anthropic,openai]` | `PydanticAIAgent` |
| `langgraph` | `ag-ui-langgraph`, `langgraph` | `LangGraphAGUIAgent` |
| `all` | both | |

## Install

=== "uv"

    ```bash
    uv init my-agent-app && cd my-agent-app
    uv add "reflex-agentkit[pydantic-ai]"
    ```

=== "pip"

    ```bash
    python -m venv .venv && . .venv/bin/activate
    pip install "reflex-agentkit[pydantic-ai]"
    ```

!!! note "Pre-releases"
    Until `0.1.0` is out, add `--prerelease=allow` (uv) or `--pre` (pip) to get the
    latest pre-release.

## A first app

Create a Reflex app (`uv run reflex init`, or `reflex init` with pip, and pick the blank
template), then replace the app module with this:

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

The components are built on Radix Themes, so enable the plugin in `rxconfig.py`:

```python
import reflex as rx

config = rx.Config(
    app_name="my_agent_app",
    plugins=[rx.plugins.RadixThemesPlugin()],
)
```

Run it with your Anthropic key:

```bash
ANTHROPIC_API_KEY=sk-ant-... uv run reflex run
```

Ask it to plan a trip. The `get_weather` call appears as a card, and the approval dialog
opens before `book_hotel` runs. You can approve, edit the arguments or reject the call.

!!! tip "No API key?"
    Use a local model: see [Local models with Ollama](guides/ollama.md). To check that
    the app compiles with no model at all, PydanticAI's `TestModel` works too.

## The three pieces

1. **The agent.** Anything that produces AG-UI events: a PydanticAI agent wrapped in
   `PydanticAIAgent`, a LangGraph graph wrapped in `LangGraphAGUIAgent`, or an AG-UI
   server reached through `HttpAGUIClient`.
2. **The state.** A class that mixes `AgentState` into `rx.State`. Configuration such as
   `agent` is class-level and annotated `ClassVar`, so it never becomes a state var that
   Reflex would send to the browser.
3. **The UI.** `agent_chat(ChatState)`, or your own components reading the state's vars
   and calling its event handlers ([Your own UI](guides/own-ui.md)).

## Next steps

- [Concepts](concepts.md) explains runs, threads, tool calls, interrupts and shared state.
- [Human in the loop](guides/human-in-the-loop.md) covers approvals and questions.
- The [Dojo examples](https://github.com/ecrespo/reflex-agentkit/tree/main/examples)
  show every feature with PydanticAI and with LangGraph.
