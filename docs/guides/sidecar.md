# Sidecar deployment

By default the agent runs **in process**: inside the Reflex backend, on its event loop.
That is the simplest deployment and the one the quickstart uses. A **sidecar** runs the
agent in its own process behind an AG-UI HTTP endpoint, and the Reflex app reaches it
with `HttpAGUIClient`. There is no other IPC: the sidecar is just an AG-UI server.

## When to use one

| Use in process when | Use a sidecar when |
|---|---|
| The agent is I/O-bound (model calls, HTTP tools) | The agent does CPU-heavy work (parsing, embeddings, local models in Python) |
| One deployment is simpler | The agent scales, deploys or restarts separately from the UI |
| The agent is written in Python with an adapter | The agent is an existing AG-UI server, in any language |

In-process agents share the event loop with every user of that Reflex worker, so they
must never block it. A sidecar removes that risk.

## Serve a PydanticAI agent

PydanticAI's `AGUIAdapter.dispatch_request` turns a request into an AG-UI stream. Mount
it in any Starlette or FastAPI app. Pass `DeferredToolRequests` in `output_type` so that
`requires_approval` tools pause the run (the in-process adapter does this for you):

```python
# agent_server.py — run with: uvicorn agent_server:app --port 8000
from fastapi import FastAPI, Request
from fastapi.responses import Response
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai.ui.ag_ui import AGUIAdapter

agent = Agent("anthropic:claude-sonnet-5-5", instructions="You book hotels.")


@agent.tool_plain(requires_approval=True)
def book_hotel(city: str) -> str:
    """Book a hotel in a city."""
    return f"Booked a hotel in {city}."


app = FastAPI()


@app.post("/agent")
async def run_agent(request: Request) -> Response:
    return await AGUIAdapter.dispatch_request(
        request, agent=agent, output_type=[agent.output_type, DeferredToolRequests]
    )
```

## Serve a LangGraph graph

ag-ui-langgraph provides the FastAPI endpoint. Wrap the graph in `LangGraphAGUIAgent` to
get the same interrupt behavior as in process:

```python
from fastapi import FastAPI
from ag_ui_langgraph import add_langgraph_fastapi_endpoint

from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent

app = FastAPI()
add_langgraph_fastapi_endpoint(app, LangGraphAGUIAgent(graph, name="travel"), "/agent")
```

## Point the Reflex app at it

```python
import os
from typing import ClassVar

import reflex as rx

from reflex_agentkit import AgentState, HttpAGUIClient


class ChatState(AgentState, rx.State):
    agent: ClassVar = HttpAGUIClient(
        "http://localhost:8000/agent",
        headers=lambda: {"Authorization": f"Bearer {os.environ['AGENT_TOKEN']}"},
    )
```

- `headers` can be a mapping or a function called before each run, for rotating tokens.
  Headers are never logged, never stored in state and never put in error messages.
- The default timeouts are 10 s to connect and 60 s between bytes of the stream; pass
  `timeout=` to change them. A stalled stream ends the run with `AGENT_STREAM_ERROR`.
- Cancelling a run closes the HTTP connection, and the server sees the disconnect.
- One client can serve every session: it holds no per-run state.

!!! warning "The agent endpoint is trusted infrastructure"
    The app validates every event, but it trusts the endpoint to be the agent you
    configured. Keep it on a private network or behind authentication. The URL is
    developer configuration, never something the browser can set.
