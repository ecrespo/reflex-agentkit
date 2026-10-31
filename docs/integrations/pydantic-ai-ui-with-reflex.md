# PydanticAI docs: "UI with Reflex" (draft)

!!! info "How to submit"
    - **Target repository:** [`pydantic/pydantic-ai`](https://github.com/pydantic/pydantic-ai)
    - **File:** `docs/ui/ag-ui.md`, a new subsection at the end of **Usage**, after
      *Stand-alone ASGI app*. No navigation change is needed (`docs/navigation.yml`
      already lists the page).
    - **PR title:** `docs(ag-ui): show a Python frontend with Reflex`
    - **When:** after `reflex-agentkit 0.1.0` is on PyPI.
    - The repo runs the examples in its docs, and its code blocks carry only a `title`.
      This one imports `reflex` and `reflex_agentkit`, which the docs tests do not
      install: ask the maintainers in the PR whether to add a skip marker or to show
      the block as plain text.

## The section

The text below uses the page's own conventions (`pip/uv-add`, admonitions).

````markdown
### Python frontend with Reflex

To build the frontend in Python as well, [reflex-agentkit](https://github.com/ecrespo/reflex-agentkit)
is an AG-UI client for [Reflex](https://reflex.dev) apps. It runs the agent in the
Reflex backend through `AGUIAdapter.run_stream()` and renders a streaming chat with tool
calls, approval of [deferred tools](../deferred-tools.md) (approve, edit the arguments or
reject), shared state and frontend tools.

```bash
pip/uv-add 'reflex-agentkit[pydantic-ai]'
```

```py {title="reflex_app.py"}
from typing import ClassVar

import reflex as rx
from pydantic_ai import Agent
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

agent = Agent('anthropic:claude-sonnet-5-5', instructions='You are a travel assistant.')


@agent.tool_plain(requires_approval=True)
def book_hotel(city: str, nights: int) -> str:
    """Book a hotel room."""
    return f'Booked {nights} nights in {city}.'


class ChatState(AgentState, rx.State):
    agent: ClassVar = PydanticAIAgent(agent)


def index() -> rx.Component:
    return agent_chat(ChatState)


app = rx.App()
app.add_page(index)
```

Tools with `requires_approval=True` open an approval dialog with no further setup, and
the run resumes with the user's decision through AG-UI interrupts. The agent can also
run in its own process behind [`AGUIAdapter.dispatch_request()`](#handle-a-starlette-request),
with the Reflex app connecting to it over HTTP.
````

## PR description

```markdown
Adds a short subsection to the AG-UI page showing a Python frontend for a Pydantic AI
agent, using reflex-agentkit (an AG-UI client for Reflex apps, MIT).

It uses `AGUIAdapter.run_stream()` in process, maps deferred tool approvals to an
approve / edit / reject dialog through AG-UI interrupts, and supports `StateDeps` shared
state and frontend tools. A five-demo port of the AG-UI Dojo for Pydantic AI is in
https://github.com/ecrespo/reflex-agentkit/tree/main/examples/pydantic_ai_dojo.
```
