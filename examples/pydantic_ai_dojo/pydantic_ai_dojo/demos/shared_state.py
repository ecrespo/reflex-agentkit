"""Shared state: a recipe that both the agent and the user edit.

The recipe lives in ``shared_state`` and is validated by ``shared_state_model``. Each run
sends it to the agent as AG-UI state (PydanticAI's ``StateDeps``); the agent's
``update_recipe`` tool sends a ``STATE_SNAPSHOT`` back. The user edits it too: renaming
the recipe writes a JSON Patch with ``patch_shared_state``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import reflex as rx
from ag_ui.core import EventType, RunAgentInput, StateSnapshotEvent
from examples_shared.models import pydantic_ai_model
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, ToolReturn
from pydantic_ai.ui import StateDeps

from pydantic_ai_dojo.layout import demo_page
from reflex_agentkit import AgentState, agent_chat
from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent


class Recipe(BaseModel):
    """The shared state."""

    title: str = "Untitled recipe"
    servings: int = 2
    ingredients: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)


recipe_agent = Agent(
    pydantic_ai_model(),
    deps_type=StateDeps[Recipe],
    instructions=(
        "You are a chef who co-writes one recipe with the user. Read the current recipe, "
        "then call `update_recipe` with the whole updated recipe whenever you change it."
    ),
    name="shared_state",
)


@recipe_agent.instructions
def current_recipe(ctx: RunContext[StateDeps[Recipe]]) -> str:
    return f"The current recipe is: {ctx.deps.state.model_dump_json()}"


@recipe_agent.tool
def update_recipe(ctx: RunContext[StateDeps[Recipe]], recipe: Recipe) -> ToolReturn:
    """Replace the shared recipe with an updated version."""
    ctx.deps.state = recipe
    snapshot = StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=recipe.model_dump())
    return ToolReturn(return_value="Recipe updated.", metadata=[snapshot])


def fresh_deps(run_input: RunAgentInput) -> StateDeps[Recipe]:
    """New deps for every run; the adapter fills ``state`` from the run input."""
    return StateDeps(Recipe())


class SharedStateState(AgentState, rx.State):
    """The conversation with ``recipe_agent`` and the recipe."""

    agent: ClassVar = PydanticAIAgent(recipe_agent, deps_factory=fresh_deps)
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


def recipe_panel() -> rx.Component:
    """The recipe as the user sees it, with a rename form."""
    recipe = SharedStateState.shared_state
    return rx.card(
        rx.vstack(
            rx.heading(recipe["title"].to(str), size="5"),
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
