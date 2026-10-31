"""Shared state: a recipe that lives in the graph state and in ``shared_state``.

The graph state has the recipe fields next to ``messages``. Each run sends
``shared_state`` as AG-UI state, so the graph reads the user's edits; the graph's
``STATE_SNAPSHOT`` (without ``messages``) comes back as ``shared_state``, validated by
``shared_state_model``. The user renames the recipe with ``patch_shared_state``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import reflex as rx
from examples_shared.models import langgraph_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from langgraph_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.langgraph import LangGraphAGUIAgent


class Recipe(BaseModel):
    """The shared state, as the app sees it."""

    title: str = "Untitled recipe"
    servings: int = 2
    ingredients: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)


class RecipeGraphState(MessagesState, total=False):
    """The graph state: the conversation plus the recipe fields."""

    title: str
    servings: int
    ingredients: list[str]
    steps: list[str]


@tool(args_schema=Recipe)
def update_recipe(**recipe: Any) -> str:
    """Replace the shared recipe with an updated version (all fields)."""
    return "Recipe updated."


def build_graph(model: BaseChatModel) -> CompiledStateGraph[Any, Any, Any, Any]:
    bound = model.bind_tools([update_recipe])

    async def chef(state: RecipeGraphState) -> dict[str, Any]:
        current = Recipe.model_validate(
            {k: v for k, v in state.items() if k in Recipe.model_fields}
        )
        prompt = (
            "You are a chef who co-writes one recipe with the user. Call `update_recipe` with "
            "the whole recipe whenever you change it. "
            f"The current recipe: {current.model_dump_json()}"
        )
        reply = await bound.ainvoke([SystemMessage(content=prompt), *state["messages"]])
        return {"messages": [reply]}

    def apply(state: RecipeGraphState) -> dict[str, Any]:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            raise TypeError("expected the model's tool calls")
        call = last.tool_calls[0]
        recipe = Recipe.model_validate(call["args"])
        done = ToolMessage(content="Recipe updated.", tool_call_id=str(call["id"]))
        return {**recipe.model_dump(), "messages": [done]}

    def route(state: RecipeGraphState) -> str:
        return "apply" if getattr(state["messages"][-1], "tool_calls", None) else END

    builder = StateGraph(RecipeGraphState)
    builder.add_node("chef", chef)
    builder.add_node("apply", apply)
    builder.add_edge(START, "chef")
    builder.add_conditional_edges("chef", route, ["apply", END])
    builder.add_edge("apply", "chef")
    return builder.compile(checkpointer=InMemorySaver())


class SharedStateState(AgentState, rx.State):
    """The conversation with the chef graph and the recipe."""

    agent: ClassVar = LangGraphAGUIAgent(build_graph(langgraph_model()), name="chef")
    shared_state_model: ClassVar = Recipe

    @rx.event
    def rename(self, form: dict[str, Any]) -> Any:
        """Rename the recipe from the side panel."""
        title = str(form.get("title", "")).strip()
        if not title:
            return None
        return SharedStateState.patch_shared_state(
            [{"op": "add", "path": "/title", "value": title}]
        )


STATE = SharedStateState


def recipe_panel() -> rx.Component:
    """The recipe as the user sees it, with a rename form."""
    recipe = SharedStateState.shared_state
    return rx.card(
        rx.vstack(
            rx.heading(
                rx.cond(recipe["title"], recipe["title"].to(str), "No recipe yet"), size="5"
            ),
            rx.text("Serves ", recipe["servings"].to_string()),
            rx.heading("Ingredients", size="3"),
            rx.unordered_list(rx.foreach(recipe["ingredients"].to(list[str]), rx.list_item)),
            rx.heading("Steps", size="3"),
            rx.ordered_list(rx.foreach(recipe["steps"].to(list[str]), rx.list_item)),
            rx.form(
                rx.hstack(
                    rx.input(name="title", placeholder="New title", aria_label="Recipe title"),
                    rx.button("Rename", type="submit", disabled=~SharedStateState.can_send),
                ),
                on_submit=SharedStateState.rename,
                reset_on_submit=True,
            ),
            spacing="2",
        ),
        width="100%",
    )


def page() -> rx.Component:
    return demo_page(
        "Shared state",
        "Ask the chef for a recipe, then rename it yourself and ask for changes.",
        rx.grid(
            agent_chat(SharedStateState, placeholder="A quick vegetarian pasta, please"),
            recipe_panel(),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="4",
            width="100%",
        ),
    )
