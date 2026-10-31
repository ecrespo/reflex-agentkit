"""Import guard for the optional adapters (REQ-031.3, API §7.7)."""

from __future__ import annotations

import importlib

from reflex_agentkit.core.errors import AdapterNotInstalledError

__all__ = ["require"]


def require(extra: str, *modules: str) -> None:
    """Import ``modules`` or raise ``AdapterNotInstalledError`` naming the extra to install.

    Args:
        extra: The package extra, e.g. ``"pydantic-ai"``; the adapter module is
            ``reflex_agentkit.adapters.<extra with "_" for "-">``.
        modules: The modules the adapter needs.
    """
    adapter = f"reflex_agentkit.adapters.{extra.replace('-', '_')}"
    for module in modules:
        try:
            importlib.import_module(module)
        except ImportError:
            raise AdapterNotInstalledError(
                f"{adapter} requires the '{extra}' extra: pip install 'reflex-agentkit[{extra}]'"
            ) from None
