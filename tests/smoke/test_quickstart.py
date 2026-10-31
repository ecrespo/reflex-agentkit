"""The quickstart example: size, README copy, compile and a driven turn (T-040).

REQ-029.1-3, REQ-030.2. ``AGENTKIT_MODEL=test`` makes ``examples/quickstart/rxconfig.py``
swap every PydanticAI model for ``TestModel``, so nothing here needs a network or a key.
"""

from __future__ import annotations

import importlib
import os
import re
import runpy
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from helpers.reflex_harness import ReflexHarness

from reflex_agentkit.core.models import RunStatus, ToolCallStatus

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "quickstart"
QUICKSTART = EXAMPLE / "quickstart" / "quickstart.py"
README_BLOCK = re.compile(
    r"<!-- quickstart:start -->\s*```python\n(?P<code>.*?)```\s*<!-- quickstart:end -->",
    re.DOTALL,
)


def counted_lines(source: str) -> int:
    """Non-blank, non-comment lines (REQ-029.1)."""
    return sum(
        1 for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )


def test_REQ_029_1_quickstart_line_count() -> None:
    """REQ-029.1: the quickstart has at most 30 counted lines (API §2 says 23)."""
    source = QUICKSTART.read_text(encoding="utf-8")
    assert counted_lines(source) <= 30
    assert "requires_approval=True" in source  # one approval-required tool
    assert "@travel_agent.tool_plain\n" in source  # one visible tool call


def test_REQ_029_3_readme_matches_quickstart() -> None:
    """REQ-029.3: the README carries the quickstart verbatim."""
    match = README_BLOCK.search((ROOT / "README.md").read_text(encoding="utf-8"))
    assert match is not None, "README.md has no quickstart block"
    assert match["code"] == QUICKSTART.read_text(encoding="utf-8")


def test_REQ_029_3_quickstart_matches_the_api_spec() -> None:
    """API §2 is normative: the example is the spec's block verbatim."""
    spec = (ROOT / "specs" / "api" / "agentkit-python-api-v1.md").read_text(encoding="utf-8")
    section = spec.split("## 2. The quickstart", 1)[1]
    block = section.split("```python\n", 1)[1].split("```", 1)[0]
    assert block == QUICKSTART.read_text(encoding="utf-8")


@pytest.mark.slow
def test_REQ_029_2_quickstart_compiles_without_network_or_keys() -> None:
    """REQ-029.2, REQ-030.2: ``reflex compile --dry`` succeeds offline (TD OQ-2)."""
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    env |= {"AGENTKIT_MODEL": "test", "PYDANTIC_AI_NO_BANNER": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "reflex", "compile", "--dry", "--no-rich"],
        cwd=EXAMPLE,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "compiled successfully" in result.stdout


@pytest.fixture
def quickstart(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """The quickstart module imported with the ``TestModel`` swap of ``rxconfig.py``."""
    monkeypatch.setenv("AGENTKIT_MODEL", "test")
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    from pydantic_ai import models

    monkeypatch.setattr(models, "infer_model", models.infer_model)  # restored afterwards
    runpy.run_path(str(EXAMPLE / "rxconfig.py"))
    monkeypatch.syspath_prepend(str(EXAMPLE))
    yield importlib.import_module("quickstart.quickstart")


async def test_REQ_029_1_quickstart_streams_a_tool_and_asks_for_approval(
    quickstart: Any, reflex_harness: ReflexHarness
) -> None:
    """REQ-029.1: one visible tool call, then the approval dialog for ``book_hotel``."""
    chat = quickstart.ChatState
    await reflex_harness.call("qs", chat, "send_message", text="Plan a trip to Lisbon")
    state = await reflex_harness.state("qs", chat)
    assert state.run_status == RunStatus.AWAITING_INPUT
    assert [c.name for c in state.pending_approvals] == ["book_hotel"]
    weather = [c for c in state.tool_calls if c.name == "get_weather"]
    assert [c.status for c in weather] == [ToolCallStatus.DONE]

    call_id = state.pending_approvals[0].id
    await reflex_harness.call("qs", chat, "approve_tool", call_id=call_id)
    state = await reflex_harness.state("qs", chat)
    assert state.run_status == RunStatus.IDLE
    hotel = next(c for c in state.tool_calls if c.name == "book_hotel")
    assert hotel.status == ToolCallStatus.DONE
    assert "Booked" in (hotel.result or "")
