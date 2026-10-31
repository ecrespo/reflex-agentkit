# reflex-agentkit

**The production UI layer for Python AI agents.** reflex-agentkit gives an agent a
streaming chat, tool-call cards, human-in-the-loop approvals and shared state, in pure
Python, on [Reflex](https://reflex.dev). It speaks the
[AG-UI protocol](https://docs.ag-ui.com), so it works with PydanticAI, LangGraph and any
AG-UI-compatible agent server. There is no TypeScript to write.

```python
from typing import ClassVar

import reflex as rx
from pydantic_ai import Agent

from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

travel_agent = Agent("anthropic:claude-sonnet-5-5", instructions="You are a travel assistant.")


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

## What you get

| Feature | How |
|---|---|
| Streaming replies | Markdown that streams token by token, batched to at most one push per 50 ms |
| Tool calls | A card per call with its arguments, status and result; custom renderers per tool |
| Approvals | Approve, edit the arguments or reject a tool call before it runs |
| Questions from the agent | AG-UI standard interrupts, answered with a form you can replace |
| Shared state | The agent's state mirrored in `shared_state`, editable by the app |
| Client tools | Tools the agent calls that run in your Reflex app, for example to draw a chart |
| Cancellation | A stop button that really stops the agent, within one second |
| Any AG-UI agent | In process (PydanticAI, LangGraph) or over HTTP (`HttpAGUIClient`) |

## Where to go next

- [Getting started](getting-started.md): install it and run the quickstart.
- [Concepts](concepts.md): runs, threads, tool calls, interrupts and shared state.
- [Security model](security.md): what reaches the browser, and what never does.
- [Examples](https://github.com/ecrespo/reflex-agentkit/tree/main/examples): the
  quickstart and the five AG-UI Dojo demos for PydanticAI and LangGraph.
