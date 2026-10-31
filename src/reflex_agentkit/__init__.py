"""reflex-agentkit: the production UI layer for Python AI agents, built on Reflex and AG-UI.

Reflex-dependent names (``AgentState``, components) are re-exported lazily through a
module-level ``__getattr__`` (PEP 562), so ``import reflex_agentkit.core`` never imports
``reflex`` (API §1, Constitution Art. 5).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from reflex_agentkit.core import (
    AgentClient,
    AgentKitError,
    AgentSource,
    AGUIAgent,
    ClientTool,
    ConfigurationError,
    ErrorCode,
    HttpAGUIClient,
    InProcessAGUIClient,
    RunStatus,
    ToolCallStatus,
    client_tool,
)

if TYPE_CHECKING:  # type checkers see the lazy names; runtime imports them on first use
    from reflex_agentkit.components.chat import agent_chat as agent_chat
    from reflex_agentkit.state.agent_state import AgentState as AgentState

__version__ = "0.1.0a1"

# Public name -> module that defines it (API §1, §3).
_LAZY_EXPORTS: dict[str, str] = {
    "AgentState": "reflex_agentkit.state.agent_state",
    "agent_chat": "reflex_agentkit.components.chat",
}

__all__ = [
    "AGUIAgent",
    "AgentClient",
    "AgentKitError",
    "AgentSource",
    "ClientTool",
    "ConfigurationError",
    "ErrorCode",
    "HttpAGUIClient",
    "InProcessAGUIClient",
    "RunStatus",
    "ToolCallStatus",
    "__version__",
    "client_tool",
    *_LAZY_EXPORTS,
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY_EXPORTS})
