"""Self-test of the fake AG-UI SSE server (T-021, TD DD-010)."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import httpx
from ag_ui.core import RunFinishedEvent, RunStartedEvent, TextMessageChunkEvent
from helpers.fake_server import FakeServer, Step, close, content_type, hang, send, sleep, status

from reflex_agentkit.core.clients.sse import SSEParser

Factory = Callable[[Sequence[Step]], FakeServer]


async def test_streams_events_and_records_the_request(fake_agui_server: Factory) -> None:
    server = fake_agui_server(
        [
            send(RunStartedEvent(thread_id="t", run_id="r")),
            send(TextMessageChunkEvent(message_id="m", delta="hi")),
            sleep(0.01),
            send(RunFinishedEvent(thread_id="t", run_id="r")),
        ]
    )
    parser = SSEParser()
    frames: list[str] = []
    async with (
        httpx.AsyncClient() as client,
        client.stream("POST", server.url, json={"threadId": "t"}, headers={"X-Key": "k"}) as resp,
    ):
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/event-stream"
        async for chunk in resp.aiter_bytes():
            frames.extend(parser.feed(chunk))
    assert [json.loads(f)["type"] for f in frames] == [
        "RUN_STARTED",
        "TEXT_MESSAGE_CHUNK",
        "RUN_FINISHED",
    ]
    [request] = server.requests
    assert (request.method, request.path, request.body) == ("POST", "/agent", {"threadId": "t"})
    assert request.headers["x-key"] == "k"
    assert not server.disconnected.is_set()


async def test_observes_the_disconnect_when_the_client_closes_early(
    fake_agui_server: Factory,
) -> None:
    server = fake_agui_server(
        [send({"type": "RUN_STARTED", "threadId": "t", "runId": "r"}), hang()]
    )
    async with httpx.AsyncClient() as client, client.stream("POST", server.url, json={}) as resp:
        async for _ in resp.aiter_bytes():
            break
    assert server.disconnected.wait(1.0)


async def test_status_and_content_type_steps(fake_agui_server: Factory) -> None:
    server = fake_agui_server([status(503), content_type("text/plain"), send("busy"), close()])
    async with httpx.AsyncClient() as client:
        resp = await client.post(server.url, content=b"not json")
    assert resp.status_code == 503
    assert resp.headers["content-type"] == "text/plain"
    assert server.requests[0].body == "not json"
