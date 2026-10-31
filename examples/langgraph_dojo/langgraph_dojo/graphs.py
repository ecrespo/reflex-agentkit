"""The classic LangGraph agent loop, shared by the simpler demos."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition


def chat_graph(
    model: BaseChatModel, tools: Sequence[BaseTool], instructions: str
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """``chat`` calls the model with the tools; ``tools`` runs them; repeat until done."""
    bound = model.bind_tools(list(tools))

    async def chat(state: MessagesState) -> dict[str, Any]:
        reply = await bound.ainvoke([SystemMessage(content=instructions), *state["messages"]])
        return {"messages": [reply]}

    builder = StateGraph(MessagesState)
    builder.add_node("chat", chat)
    builder.add_node("tools", ToolNode(list(tools)))
    builder.add_edge(START, "chat")
    builder.add_conditional_edges("chat", tools_condition)
    builder.add_edge("tools", "chat")
    return builder.compile(checkpointer=InMemorySaver())
