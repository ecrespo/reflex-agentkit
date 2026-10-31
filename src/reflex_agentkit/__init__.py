"""reflex-agentkit: the production UI layer for Python AI agents, built on Reflex and AG-UI.

Reflex-dependent names (``AgentState``, components) are re-exported lazily through a
module-level ``__getattr__`` (PEP 562), so ``import reflex_agentkit.core`` never imports
``reflex`` (API §1, Constitution Art. 5).
"""

from __future__ import annotations

import importlib
from typing import Any

from reflex_agentkit.core import (
    AgentKitError,
    ConfigurationError,
    ErrorCode,
    RunStatus,
    ToolCallStatus,
)

__version__ = "0.1.0.dev0"

# Public name -> module that defines it. Filled in as the state/components tasks land.
_LAZY_EXPORTS: dict[str, str] = {}

__all__ = [
    "AgentKitError",
    "ConfigurationError",
    "ErrorCode",
    "RunStatus",
    "ToolCallStatus",
    "__version__",
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
