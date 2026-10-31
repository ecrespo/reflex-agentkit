"""Secret hygiene: nothing configured reaches the browser (T-031, REQ-025.2)."""

from __future__ import annotations

from typing import Any

import reflex as rx
from helpers.fake_server import FakeServer, reply
from helpers.reflex_harness import ReflexHarness
from reflex.istate.manager.token import BaseStateToken
from reflex_base.utils.format import json_dumps

from reflex_agentkit import AgentState, HttpAGUIClient
from reflex_agentkit.core.models import RunStatus

SECRET = "SECRET-123"  # noqa: S105 - the canary value the test looks for


def _ids(body: Any) -> dict[str, str]:
    return {"threadId": body["threadId"], "runId": body["runId"]}


async def test_REQ_025_2_client_visible_state_has_no_secrets(
    fake_agui_server: Any, reflex_harness: ReflexHarness
) -> None:
    """REQ-025.1-2: after a full run, neither the state nor any delta holds the header."""
    server: FakeServer = fake_agui_server(
        [
            reply(lambda b: {"type": "RUN_STARTED", **_ids(b)}),
            reply(lambda b: {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"}),
            reply(lambda b: {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "hi"}),
            reply(lambda b: {"type": "TEXT_MESSAGE_END", "messageId": "m1"}),
            reply(lambda b: {"type": "RUN_FINISHED", **_ids(b)}),
        ]
    )
    client = HttpAGUIClient(server.url, headers={"Authorization": f"Bearer {SECRET}"})
    namespace = {"__annotations__": {"agent": "ClassVar"}, "agent": client, "__module__": __name__}
    cls = type("SecretHygieneState", (AgentState, rx.State), namespace)
    try:
        await reflex_harness.call("tok", cls, "send_message", text="hello")
    finally:
        await client.aclose()
    state: AgentState = await reflex_harness.state("tok", cls)
    assert state.run_status == RunStatus.IDLE
    assert server.requests[0].headers["authorization"] == f"Bearer {SECRET}"  # configured

    root = await reflex_harness.manager.get_state(BaseStateToken(ident="tok", cls=cls))
    assert SECRET not in json_dumps(root.dict())
    deltas = reflex_harness.deltas_for("tok")
    assert deltas
    assert all(SECRET not in json_dumps(delta) for delta in deltas)
