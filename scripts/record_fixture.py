"""Record a DM §10 JSON Lines fixture from a real adapter run (T-035).

Usage::

    uv run python scripts/record_fixture.py --adapter pydantic-ai --scenario approval \\
        [--out tests/fixtures/events/pydantic_ai_approval_recorded.jsonl]

The adapter runs offline with a test model. Its events go through the real reducer and
commands, and the file gets a header whose ``expect`` is the resulting state, with the
thread and run IDs replaced by ``$thread``, ``$run`` and ``$run2``. Review and trim a
recorded fixture by hand before committing it (DM §10).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from ag_ui.core import BaseEvent, RunAgentInput

from reflex_agentkit.core.commands import apply_approval, begin_run
from reflex_agentkit.core.conversation import ConversationState
from reflex_agentkit.core.models import ReducerConfig
from reflex_agentkit.core.reducer import reduce
from reflex_agentkit.core.run_input import RunInputBuilder

Run = Callable[[RunAgentInput], AsyncIterator[BaseEvent]]
Line = dict[str, Any]


def _pydantic_ai_approval() -> tuple[Run, str]:
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    from reflex_agentkit.adapters.pydantic_ai import PydanticAIAgent

    agent = Agent(TestModel(call_tools=["book_hotel"]), output_type=str)

    @agent.tool_plain(requires_approval=True)
    def book_hotel(city: str) -> str:
        """Book a hotel."""
        return f"booked {city}"

    return PydanticAIAgent(agent).run, "book a hotel"


SCENARIOS: dict[tuple[str, str], Callable[[], tuple[Run, str]]] = {
    ("pydantic-ai", "approval"): _pydantic_ai_approval,
}


def _wire(event: BaseEvent) -> Line:
    line: Line = event.model_dump(mode="json", by_alias=True, exclude_none=True)
    line.pop("timestamp", None)
    return line


async def _stream(run: Run, conv: ConversationState) -> tuple[ConversationState, list[Line]]:
    lines: list[Line] = []
    async for event in run(RunInputBuilder().build(conv)):
        lines.append(_wire(event))
        conv = reduce(conv, event)
    return conv, lines


async def record(adapter: str, scenario: str) -> list[Line]:
    """Run the scenario and return the fixture lines (header first)."""
    run, user_text = SCENARIOS[(adapter, scenario)]()
    config = ReducerConfig()
    conv = begin_run(ConversationState.initial(config), config=config, user_text=user_text)
    ids = {conv.thread_id: "$thread", conv.run_id: "$run"}
    conv, lines = await _stream(run, conv)
    codes = [d.code.value for d in conv.diagnostics]
    for call in [c for c in conv.tool_calls if c.status.value == "pending_approval"]:
        lines.append({"$command": "approve_tool", "call_id": call.id})
        conv = apply_approval(conv, call.id)
    if any(line.get("$command") for line in lines):
        lines.append({"$command": "begin_run", "resume": True})
        conv = begin_run(conv, config=config, resume=True)
        ids[conv.run_id] = "$run2"
        conv, more = await _stream(run, conv)
        lines += more
        codes += [d.code.value for d in conv.diagnostics]
    expect: Line = {
        "run_status": conv.run_status.value,
        "tool_calls": [
            {"id": c.id, "name": c.name, "status": c.status.value, "result": c.result}
            for c in conv.tool_calls
        ],
        "messages.length": len(conv.messages),
        "diagnostics.codes": codes,
    }
    header: Line = {
        "fixture": f"{adapter.replace('-', '_')}_{scenario}_recorded",
        "reqs": ["REQ-005.3", "REQ-022.2"],
        "start": {"user_text": user_text},
        "expect": expect,
    }
    text = json.dumps([header, *lines])
    for real, placeholder in ids.items():
        text = text.replace(json.dumps(real)[1:-1], placeholder)
    restored: list[Line] = json.loads(text)
    return restored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--adapter", required=True, choices=sorted({a for a, _ in SCENARIOS}))
    parser.add_argument("--scenario", required=True, choices=sorted({s for _, s in SCENARIOS}))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    lines = asyncio.run(record(args.adapter, args.scenario))
    text = "".join(json.dumps(line) + "\n" for line in lines)
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
