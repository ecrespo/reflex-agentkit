"""The public surface of API §3 and the lazy top-level re-exports of API §1 (T-039)."""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest

_TOP = {
    "AgentState",
    "agent_chat",
    "client_tool",
    "ClientTool",
    "HttpAGUIClient",
    "InProcessAGUIClient",
    "AgentClient",
    "AGUIAgent",
    "AgentSource",
    "RunStatus",
    "ToolCallStatus",
    "ErrorCode",
    "AgentKitError",
    "ConfigurationError",
    "__version__",
}
_CORE = (_TOP - {"AgentState", "agent_chat", "__version__"}) | {
    "reduce",
    "ConversationState",
    "Diagnostic",
    "ChatMessage",
    "ToolCall",
    "PendingInterrupt",
    "CustomEventRecord",
    "RunInputBuilder",
    "AgentHTTPError",
    "AgentStreamError",
    "AdapterNotInstalledError",
}
_COMPONENTS = {
    "agent_chat",
    "message_list",
    "composer",
    "tool_call_card",
    "approval_dialog",
    "run_status_bar",
    "shared_state_panel",
    "ToolRenderer",
    "InterruptRenderer",
}

SURFACE = {
    "reflex_agentkit": _TOP,
    "reflex_agentkit.core": _CORE,
    "reflex_agentkit.components": _COMPONENTS,
    "reflex_agentkit.adapters.pydantic_ai": {"PydanticAIAgent"},
}


@pytest.mark.parametrize("module_name", sorted(SURFACE))
def test_API_3_all_matches_the_public_surface(module_name: str) -> None:
    """API §3: each module's ``__all__`` is exactly the documented table row."""
    module = importlib.import_module(module_name)
    assert set(module.__all__) == SURFACE[module_name]
    assert len(module.__all__) == len(set(module.__all__))
    for name in module.__all__:
        assert getattr(module, name) is not None


def test_API_3_top_level_names_are_the_same_objects_as_their_home_modules() -> None:
    """API §1: the lazy re-exports resolve to the defining objects."""
    import reflex_agentkit
    from reflex_agentkit import components, core

    assert reflex_agentkit.agent_chat is components.agent_chat
    for name in _CORE & _TOP:
        assert getattr(reflex_agentkit, name) is getattr(core, name)
    assert isinstance(reflex_agentkit.__version__, str)
    assert {"AgentState", "agent_chat"} <= set(dir(reflex_agentkit))


def test_API_1_unknown_top_level_attribute_raises() -> None:
    import reflex_agentkit

    with pytest.raises(AttributeError):
        _ = reflex_agentkit.does_not_exist


def test_REQ_031_2_importing_core_does_not_import_reflex() -> None:
    """API §1, REQ-031.2: ``import reflex_agentkit.core`` leaves reflex unloaded."""
    code = (
        "import sys, reflex_agentkit.core, reflex_agentkit\n"
        "assert 'reflex' not in sys.modules, 'reflex imported'\n"
        "assert 'reflex_agentkit.state' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603  (fixed code)
