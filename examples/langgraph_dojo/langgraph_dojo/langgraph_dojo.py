"""The LangGraph Dojo app: one page per AG-UI Dojo demo."""

import reflex as rx

from langgraph_dojo.demos import (
    agentic_chat,
    backend_tools,
    generative_ui,
    human_in_the_loop,
    shared_state,
)
from langgraph_dojo.layout import index

app = rx.App()
app.add_page(index, route="/", title="Dojo · LangGraph")
app.add_page(agentic_chat.page, route="/agentic-chat", title="Agentic chat")
app.add_page(backend_tools.page, route="/backend-tools", title="Backend tool rendering")
app.add_page(human_in_the_loop.page, route="/human-in-the-loop", title="Human in the loop")
app.add_page(shared_state.page, route="/shared-state", title="Shared state")
app.add_page(generative_ui.page, route="/generative-ui", title="Tool-based generative UI")
