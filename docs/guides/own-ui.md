# Your own UI

`agent_chat` is optional. `AgentState` is a plain Reflex state: read its vars, call its
event handlers, and build any UI you like from Reflex components.

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

## Mixing in the components

Each part of `agent_chat` is a component of its own, so you can use only the pieces you
need: `message_list`, `composer`, `tool_call_card`, `approval_dialog`, `run_status_bar` and
`shared_state_panel`. They all take the state class first. See
[Components](../reference/components.md).

```python
from reflex_agentkit.components import approval_dialog, composer, message_list


def index() -> rx.Component:
    return rx.container(
        rx.heading("Support"),
        message_list(ChatState),
        composer(ChatState, placeholder="Describe the problem"),
        approval_dialog(ChatState),
    )
```

## Per-user clients and run input

Override the hooks to adapt each run to the signed-in user. They are plain methods, not
event handlers, and the browser can never call them.

```python
class ChatState(AgentState, rx.State):
    def create_client(self) -> HttpAGUIClient:
        token = lookup_token(self.router.session.client_token)  # your own backend lookup
        return HttpAGUIClient(
            "https://agents.internal/support",
            headers={"Authorization": f"Bearer {token}"},
        )

    def prepare_run_input(self, run_input):
        return run_input.model_copy(update={"forwarded_props": {"locale": "es"}})

    async def on_run_end(self, status) -> None:
        record_metrics(self.thread_id, status)  # must be quick: it runs under the state lock
```

The client a hook returns lives only in backend memory: it never becomes a state var.
