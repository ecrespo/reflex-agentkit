"""Shared checks for the Dojo examples (REQ-030.1-2)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMOS = ("agentic_chat", "backend_tools", "human_in_the_loop", "shared_state", "generative_ui")


def counted_lines(path: Path) -> int:
    """Non-blank, non-comment lines."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return sum(1 for line in lines if line.strip() and not line.lstrip().startswith("#"))


def compile_offline(example: Path) -> subprocess.CompletedProcess[str]:
    """``reflex compile --dry`` with the offline test model and no API keys (TD OQ-2)."""
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env |= {"AGENTKIT_MODEL": "test", "PYDANTIC_AI_NO_BANNER": "1"}
    return subprocess.run(
        [sys.executable, "-m", "reflex", "compile", "--dry", "--no-rich"],
        cwd=example,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
