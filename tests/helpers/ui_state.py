"""A configured state class and a render helper for component tests."""

from __future__ import annotations

from typing import ClassVar

import reflex as rx

from helpers.fake_clients import ScriptedClient, finished, started
from reflex_agentkit import AgentState


class UIState(AgentState, rx.State):
    agent: ClassVar = ScriptedClient([started(), finished()])


def render(component: rx.Component) -> str:
    """The component compiled to its JSX-like string, plus its hooks.

    Form ``on_submit`` handlers are hoisted into hooks (``handleSubmit_…``), so the hook
    code is where their event names appear.
    """
    hooks = component._get_all_hooks()
    return str(component) + "\n" + "\n".join(hooks)
