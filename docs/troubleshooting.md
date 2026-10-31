# Troubleshooting

## `ConfigurationError: ChatState.agent must be annotated as ClassVar`

```text
ConfigurationError: ChatState.agent must be annotated as ClassVar (`agent: ClassVar = ...`),
or Reflex makes it a state var
```

Reflex turns every annotated or unannotated class attribute of a state into a state var,
which it serializes and sends to the browser. Configuration must not be one. Annotate it:

```python
from typing import ClassVar


class ChatState(AgentState, rx.State):
    agent: ClassVar = PydanticAIAgent(travel_agent)
    flush_interval_ms: ClassVar = 30
```

## `VarTypeError: State vars must be of a serializable type`

```text
VarTypeError: State vars must be of a serializable type. ... Found var "...thing_rx_state_"
with type <class 'Thing'>.
```

The same cause, on an attribute of your own: an object (a client, an agent, a connection)
assigned on a state class without `ClassVar`. Annotate it `ClassVar` if it is shared by all
sessions, or keep it outside the state. A non-picklable object (for example
`httpx.AsyncClient()`) can fail with `TypeError: cannot pickle ...` instead.

## The PydanticAI banner

PydanticAI prints an observability banner the first time an agent runs. Silence it with
the environment variable:

```bash
PYDANTIC_AI_NO_BANNER=1 uv run reflex run
```

reflex-agentkit never changes your environment, so it does not set this for you.

## The chat has no styles

The components use Radix Themes. Add the plugin in `rxconfig.py`:

```python
config = rx.Config(app_name="my_app", plugins=[rx.plugins.RadixThemesPlugin()])
```

## The approval dialog never opens

- **PydanticAI:** the tool needs `requires_approval=True`. With an AG-UI server of your
  own (a [sidecar](guides/sidecar.md)), pass `DeferredToolRequests` in `output_type`.
- **LangGraph:** the graph needs a checkpointer, and the node must call
  `request_tool_approval` (or `interrupt`).
- **Ollama and other local models:** the model must support tool calling.

## `AGENT_STREAM_ERROR` after a minute

`HttpAGUIClient` waits 60 seconds between bytes by default. For agents that think longer
without streaming, raise the read timeout:

```python
HttpAGUIClient(url, timeout=httpx.Timeout(10.0, read=300.0))
```

## `ImportError: ... requires the 'langgraph' extra`

Install the extra for the adapter you import:

```bash
uv add "reflex-agentkit[langgraph]"   # or [pydantic-ai], or [all]
```

## Everything is slow while one user streams

An in-process agent is blocking the event loop (CPU work, or a synchronous call). Move
the work to a thread (`asyncio.to_thread`), or run the agent as a
[sidecar](guides/sidecar.md).
