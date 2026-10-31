"""Assert that importing ``reflex_agentkit.core`` pulls in neither Reflex nor any extra.

Constitution Art. 1/5 and PRD REQ-031.2: the pure core must work with no extras
installed and must never import ``reflex``. Run in a fresh interpreter (CI job
``core-no-extras``); exits 1 and lists the offenders on failure.
"""

from __future__ import annotations

import importlib
import sys

FORBIDDEN = ("reflex", "pydantic_ai", "langgraph", "ag_ui_langgraph")


def leaked_modules() -> list[str]:
    """Import the core and return the forbidden top-level modules now loaded."""
    importlib.import_module("reflex_agentkit.core")
    importlib.import_module("reflex_agentkit.core.clients")
    return [name for name in FORBIDDEN if name in sys.modules]


def main() -> int:
    leaked = leaked_modules()
    if leaked:
        print(f"reflex_agentkit.core imported forbidden modules: {', '.join(leaked)}")
        return 1
    print("reflex_agentkit.core is isolated: no reflex and no extras imported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
