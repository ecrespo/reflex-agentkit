# LangGraph docs: "Frontend with Reflex" (draft)

!!! info "How to submit"
    - **Target repository:** [`langchain-ai/docs`](https://github.com/langchain-ai/docs)
      (the source of docs.langchain.com, written in Mintlify MDX)
    - **File:** a new page `src/oss/langgraph/frontend/reflex.mdx`, and its entry in
      `src/docs.json` after `"oss/python/langgraph/frontend/custom-stream-channels"` in
      the **Python** navigation only (the page is Python-specific)
    - **PR title:** `docs(langgraph): add a Python frontend page with Reflex`
    - **When:** after `reflex-agentkit 0.1.0` is on PyPI.
    - Follow the repo's contributing guide; run its local preview and link checks before
      opening the PR.

## The page

````mdx
---
title: Frontend with Reflex
description: Build a LangGraph frontend in Python with Reflex and the AG-UI protocol
---

[Reflex](https://reflex.dev) builds web apps in pure Python. With
[reflex-agentkit](https://github.com/ecrespo/reflex-agentkit), a Reflex app becomes a
frontend for a LangGraph graph: streaming messages, a card per tool call, interrupts
answered from the UI, and the graph's state shown next to the chat. It uses the
[AG-UI protocol](https://docs.ag-ui.com) through the official `ag-ui-langgraph`
integration, so no JavaScript is needed.

## Install

```bash
pip install "reflex-agentkit[langgraph]"
```

## Connect a graph

Wrap a compiled graph in `LangGraphAGUIAgent`. The graph needs a checkpointer, because
interrupts resume from the checkpoint.

```python
from typing import ClassVar

import reflex as rx
from langgraph.checkpoint.memory import InMemorySaver
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent

graph = builder.compile(checkpointer=InMemorySaver())


class ChatState(AgentState, rx.State):
    agent: ClassVar = LangGraphAGUIAgent(graph, name="assistant")


def index() -> rx.Component:
    return agent_chat(ChatState)


app = rx.App()
app.add_page(index)
```

One instance serves every browser session; each run works on its own copy.

## Interrupts

An [`interrupt()`](/oss/python/langgraph/interrupts) in a node shows up in the chat's
dialog. The user's answer resumes the graph with `Command(resume=answer)`:

```python
from langgraph.types import interrupt


def ask_dates(state):
    nights = interrupt({"reason": "question", "message": "How many nights?"})
    return {"nights": int(nights)}
```

To approve a tool call, call `request_tool_approval` in the node that runs it. The UI
shows the call with approve, edit and reject buttons, and the node receives the decision:

```python
from reflex_agentkit.adapters.langgraph import request_tool_approval


def book(state):
    call = state["messages"][-1].tool_calls[0]
    decision = request_tool_approval(str(call["id"]), call["name"], call["args"])
    if not decision.approved:
        return {"messages": [ToolMessage("Booking rejected.", tool_call_id=call["id"])]}
    return {"messages": [ToolMessage(book_trip(**decision.args), tool_call_id=call["id"])]}
```

Several interrupts in one step are answered one at a time and resumed together, each
node receiving its own answer.

## State and frontend tools

The graph's state (without `messages`) appears in the app as `shared_state` after every
step. Tools defined in the Reflex app reach the graph in its `tools` state key when the
state schema declares one; bind them to the model to let it call them.

<Note>
The [LangGraph Dojo port](https://github.com/ecrespo/reflex-agentkit/tree/main/examples/langgraph_dojo)
shows agentic chat, backend tool rendering, human in the loop, shared state and
tool-based generative UI, each in under 200 lines of Python.
</Note>
````

## PR description

```markdown
Adds a Python frontend page for LangGraph using Reflex and reflex-agentkit (MIT), an
AG-UI client built on the official `ag-ui-langgraph` integration.

It covers connecting a compiled graph (with a checkpointer), `interrupt()` and tool
approvals answered from the UI (standard AG-UI interrupts, resumed with
`Command(resume=...)`), and shared state. Python navigation only.
```
