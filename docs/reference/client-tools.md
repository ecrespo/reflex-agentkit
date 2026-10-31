# Client tools

A client tool is a tool the agent can call that runs **in your Reflex app**, on the
server. The agent sees its definition with every run. When the model calls it, the run
ends, the library runs your handler with the arguments and starts a follow-up run with
the result, all while `run_status` stays `running`.

```python
from reflex_agentkit import client_tool


@client_tool
async def show_chart(title: str, labels: list[str], values: list[float]) -> str:
    """Show a bar chart in the chat."""
    return f"Chart {title!r} shown."


class ChatState(AgentState, rx.State):
    agent: ClassVar = ...
    client_tools: ClassVar = (show_chart,)
```

## client_tool

```python
client_tool(
    func=None,
    *,
    name: str | None = None,            # default: the function name
    description: str | None = None,     # default: the first docstring paragraph
    requires_approval: bool = False,
    timeout_s: float | None = None,     # default: AgentState.client_tool_timeout_s
) -> ClientTool
```

- The JSON Schema of the parameters comes from the type hints. A parameter without a
  hint, or with one that has no JSON Schema, raises `ConfigurationError` at decoration.
- The handler may be `async def` or plain `def`; a plain one runs in a worker thread, so
  it never blocks the event loop.
- The return value is the tool result: a `str` as is, anything else JSON-encoded, `None`
  as `""`.
- If the handler raises or times out, the call ends in `error` with the message as its
  result, and the conversation continues. It is not a run error.
- With `requires_approval=True`, the call waits for `approve_tool` / `reject_tool` before
  the handler runs.
- Handlers receive only the arguments, never the state. A handler that needs session data
  can be a closure or a method of a non-state object.

## Tool-based generative UI

A handler that only confirms, plus a [tool renderer](components.md#renderers) with the
same name, turns a tool call into UI: the card shows the chart built from the call's
arguments.

```python
def chart_card(tool_call):
    args = tool_call.args.to(dict)
    return rx.vstack(
        rx.heading(args["title"].to(str)),
        rx.foreach(args["labels"].to(list[str]), rx.text),
    )


agent_chat(ChatState, tool_renderers={"show_chart": chart_card})
```

## ClientTool

A frozen dataclass with `name`, `description`, `parameters` (the JSON Schema), `handler`,
`requires_approval` and `timeout_s`. `to_agui_tool()` returns the AG-UI `Tool` definition
sent to the agent.

With PydanticAI, client tools are exposed to the model as frontend tools. With LangGraph,
they arrive in the graph state's `tools` key when the state schema declares one; bind
them to the model there (see the
[LangGraph Dojo](https://github.com/ecrespo/reflex-agentkit/tree/main/examples/langgraph_dojo)).
