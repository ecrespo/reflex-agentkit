# Components

```python
from reflex_agentkit.components import (
    agent_chat, approval_dialog, composer, message_list,
    run_status_bar, shared_state_panel, tool_call_card,
)
```

Every component takes the state **class** first, passes standard Reflex props (`style`,
`class_name`, …) to its root element, and uses only Reflex built-in components (Radix
Themes: enable `rx.plugins.RadixThemesPlugin()`). Every control has an accessible label.

## agent_chat

```python
agent_chat(
    state,
    *,
    tool_renderers: Mapping[str, ToolRenderer] | None = None,
    interrupt_renderers: Mapping[str, InterruptRenderer] | None = None,
    show_shared_state: bool = False,
    placeholder: str = "Send a message…",
    **props,
) -> rx.Component
```

The whole chat: `run_status_bar`, `message_list`, `composer`, `approval_dialog` and, with
`show_shared_state=True`, `shared_state_panel`.

## The parts

| Component | Signature | Shows |
|---|---|---|
| `message_list` | `(state, *, tool_renderers=None, **props)` | Messages in order, Markdown for the assistant, a streaming indicator, tool cards under the message that issued them |
| `composer` | `(state, *, placeholder="Send a message…", **props)` | The message input and the Send button, disabled unless `can_send` |
| `tool_call_card` | `(state, tool_call, *, body=None, renderers=None, **props)` | A card with the tool name, a status badge, and a body: arguments and result by default |
| `approval_dialog` | `(state, *, interrupt_renderers=None, **props)` | Open while there are pending approvals or a question; one item at a time, approvals first |
| `run_status_bar` | `(state, **props)` | The run status, the current step, a Cancel button while running, and the last error |
| `shared_state_panel` | `(state, **props)` | `shared_state` as JSON, with a stale marker |

## Renderers

```python
ToolRenderer = Callable[[Var[ToolCall]], rx.Component]
InterruptRenderer = Callable[[Var[PendingInterrupt], type[AgentState]], rx.Component]
```

- **Tool renderers** are keyed by tool name and replace the *body* of the tool card; the
  header with the name and status stays. Unregistered tools use the default body.

    ```python
    def weather_card(tool_call):
        args = tool_call.args.to(dict)
        return rx.hstack(rx.icon("sun"), rx.text(args["city"].to(str)))


    agent_chat(ChatState, tool_renderers={"get_weather": weather_card})
    ```

- **Interrupt renderers** are keyed by `PendingInterrupt.reason` and replace the default
  form (a JSON editor, validated against `response_schema` when present). The renderer
  calls `state.respond_to_interrupt(payload)` itself. See
  [Human in the loop](../guides/human-in-the-loop.md#questions).

Markdown never renders raw HTML, and tool arguments and results are shown as text: markup
from the model cannot run in the browser ([Security model](../security.md)).
