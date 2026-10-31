"""``HttpAGUIClient`` against the fake AG-UI server (T-022, API §7.3, §8)."""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable, Sequence

import httpx
import pytest
from ag_ui.core import (
    BaseEvent,
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageChunkEvent,
    UserMessage,
)
from helpers.fake_server import (
    FakeServer,
    Step,
    abort,
    content_type,
    hang,
    raw,
    send,
    sleep,
    status,
)

from reflex_agentkit.core.clients.base import AgentClient
from reflex_agentkit.core.clients.http import HttpAGUIClient
from reflex_agentkit.core.errors import AgentHTTPError, AgentStreamError

Factory = Callable[[Sequence[Step]], FakeServer]
SECRET = "SECRET-123"  # noqa: S105 - a fake value the tests search for

RUN_INPUT = RunAgentInput(
    thread_id="t",
    run_id="r",
    protocol_version="1.0",
    state={},
    messages=[UserMessage(id="u1", content="hi")],
    tools=[],
    context=[],
    forwarded_props={},
)
STARTED = send(RunStartedEvent(thread_id="t", run_id="r"))
FINISHED = send(RunFinishedEvent(thread_id="t", run_id="r"))


async def _collect(client: HttpAGUIClient) -> list[BaseEvent]:
    return [event async for event in client.stream(RUN_INPUT)]


async def test_REQ_021_2_posts_the_input_and_decodes_events(fake_agui_server: Factory) -> None:
    """REQ-021.2: POST camelCase JSON with ``Accept: text/event-stream``; decode SSE."""
    server = fake_agui_server(
        [STARTED, send(TextMessageChunkEvent(message_id="m", delta="hi")), FINISHED]
    )
    client = HttpAGUIClient(server.url)
    try:
        events = await _collect(client)
    finally:
        await client.aclose()
    assert [e.type for e in events] == [
        EventType.RUN_STARTED,
        EventType.TEXT_MESSAGE_CHUNK,
        EventType.RUN_FINISHED,
    ]
    [request] = server.requests
    assert request.headers["accept"] == "text/event-stream"
    assert request.headers["content-type"] == "application/json"
    assert request.body["threadId"] == "t"
    assert request.body["runId"] == "r"
    assert request.body["forwardedProps"] == {}
    assert request.body["messages"] == [{"id": "u1", "role": "user", "content": "hi"}]
    assert "resume" not in request.body


def test_REQ_021_1_http_client_is_an_agent_client() -> None:
    """REQ-021.1: ``HttpAGUIClient`` satisfies the ``AgentClient`` protocol."""
    assert isinstance(HttpAGUIClient("http://localhost/agent"), AgentClient)


async def test_REQ_021_2_stops_reading_after_a_terminal_event(fake_agui_server: Factory) -> None:
    """API §7.2: ``RUN_ERROR``/``RUN_FINISHED`` end the stream even if the server keeps it open."""
    server = fake_agui_server([STARTED, send(RunErrorEvent(message="boom")), hang()])
    client = HttpAGUIClient(server.url)
    events = await asyncio.wait_for(_collect(client), 2)
    await client.aclose()
    assert [e.type for e in events] == [EventType.RUN_STARTED, EventType.RUN_ERROR]


async def test_REQ_021_6_static_and_callable_headers_are_sent(fake_agui_server: Factory) -> None:
    """REQ-021.6, API §7.3: callable headers are evaluated per run."""
    server = fake_agui_server([STARTED, FINISHED])
    tokens = iter(["a", "b"])
    rotating = HttpAGUIClient(
        server.url, headers=lambda: {"Authorization": f"Bearer {next(tokens)}"}
    )
    static = HttpAGUIClient(server.url, headers={"X-Api-Key": SECRET})
    await _collect(rotating)
    await _collect(rotating)
    await _collect(static)
    await rotating.aclose()
    await static.aclose()
    assert [r.headers.get("authorization") for r in server.requests[:2]] == ["Bearer a", "Bearer b"]
    assert server.requests[2].headers["x-api-key"] == SECRET


async def test_REQ_021_3_non_2xx_raises_http_error(
    fake_agui_server: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-021.3, API §8.2: status code in the error; body excerpt (≤ 1 KiB) at DEBUG."""
    server = fake_agui_server([status(503), content_type("text/plain"), raw("x" * 5000)])
    client = HttpAGUIClient(server.url)
    with (
        caplog.at_level(logging.DEBUG, logger="reflex_agentkit"),
        pytest.raises(AgentHTTPError) as info,
    ):
        await _collect(client)
    await client.aclose()
    assert info.value.status_code == 503
    assert "503" in str(info.value)
    excerpts = [r.getMessage() for r in caplog.records if "x" * 100 in r.getMessage()]
    assert excerpts
    assert all(len(m) < 1024 + 200 for m in excerpts)


async def test_REQ_021_2_wrong_content_type_raises(fake_agui_server: Factory) -> None:
    """API §8.2: 2xx with another content type is a stream error."""
    server = fake_agui_server([content_type("application/json"), raw("{}")])
    client = HttpAGUIClient(server.url)
    with pytest.raises(AgentStreamError) as info:
        await _collect(client)
    await client.aclose()
    assert info.value.reason == "content_type"


async def test_REQ_021_4_read_timeout_raises(fake_agui_server: Factory) -> None:
    """REQ-021.4: no bytes for ``timeout.read`` seconds ends the run with an error."""
    server = fake_agui_server([STARTED, sleep(3), FINISHED])
    client = HttpAGUIClient(server.url, timeout=httpx.Timeout(5.0, read=0.2))
    events: list[BaseEvent] = []
    with pytest.raises(AgentStreamError) as info:
        async for event in client.stream(RUN_INPUT):
            events.append(event)
    await client.aclose()
    assert info.value.reason == "timeout"
    assert [e.type for e in events] == [EventType.RUN_STARTED]


async def test_REQ_004_4_eof_before_a_terminal_event_raises(fake_agui_server: Factory) -> None:
    """REQ-004.4: the stream ending without ``RUN_FINISHED``/``RUN_ERROR`` is an error."""
    server = fake_agui_server([STARTED, raw('data: {"type": "RUN_FINISHED"')])
    client = HttpAGUIClient(server.url)
    with pytest.raises(AgentStreamError) as info:
        await _collect(client)
    await client.aclose()
    assert info.value.reason == "eof"


async def test_REQ_021_4_connection_dropped_mid_stream_raises(fake_agui_server: Factory) -> None:
    """REQ-021.4: a dropped connection mid-run is a stream error."""
    server = fake_agui_server([STARTED, abort()])
    client = HttpAGUIClient(server.url)
    with pytest.raises(AgentStreamError) as info:
        await _collect(client)
    await client.aclose()
    assert info.value.reason == "eof"
    assert "connection to the agent lost" in str(info.value)


async def test_REQ_021_4_connection_refused_raises_connect_error() -> None:
    """REQ-021.4: an unreachable endpoint is a stream error, not a raw httpx error."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = HttpAGUIClient(f"http://127.0.0.1:{port}/agent")
    with pytest.raises(AgentStreamError) as info:
        await _collect(client)
    await client.aclose()
    assert info.value.reason == "connect"


async def test_REQ_012_3_invalid_events_and_frames_are_skipped(
    fake_agui_server: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-012.3: invalid JSON and invalid events are skipped with warnings."""
    server = fake_agui_server(
        [
            STARTED,
            send("{not json"),
            send({"type": "TEXT_MESSAGE_CONTENT", "messageId": "m"}),
            FINISHED,
        ]
    )
    client = HttpAGUIClient(server.url)
    with caplog.at_level(logging.WARNING, logger="reflex_agentkit"):
        events = await _collect(client)
    await client.aclose()
    assert [e.type for e in events] == [EventType.RUN_STARTED, EventType.RUN_FINISHED]
    assert len(caplog.records) == 2


async def test_REQ_007_2_cancel_closes_upstream(fake_agui_server: Factory) -> None:
    """REQ-007.2: cancelling the consumer closes the connection; the server sees it."""
    server = fake_agui_server([STARTED, hang()])
    client = HttpAGUIClient(server.url)
    first = asyncio.Event()

    async def consume() -> None:
        async for _ in client.stream(RUN_INPUT):
            first.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(first.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert server.disconnected.wait(1.0)
    await client.aclose()


async def test_REQ_007_2_aclose_of_the_iterator_closes_upstream(fake_agui_server: Factory) -> None:
    """API §7.2: ``aclose()`` on the iterator also closes the upstream."""
    server = fake_agui_server([STARTED, hang()])
    client = HttpAGUIClient(server.url)
    stream = client.stream(RUN_INPUT)
    await anext(stream)
    await stream.aclose()  # type: ignore[attr-defined]
    assert server.disconnected.wait(1.0)
    await client.aclose()


async def test_REQ_021_aclose_is_idempotent_and_spares_injected_clients(
    fake_agui_server: Factory,
) -> None:
    """API §7.2-7.3: ``aclose`` twice is fine; a caller-owned client stays open."""
    server = fake_agui_server([STARTED, FINISHED])
    owned = HttpAGUIClient(server.url)
    await _collect(owned)
    await owned.aclose()
    await owned.aclose()
    async with httpx.AsyncClient() as http:
        injected = HttpAGUIClient(server.url, http_client=http)
        await _collect(injected)
        await injected.aclose()
        assert not http.is_closed
        await _collect(injected)


async def test_REQ_021_6_headers_never_leak(
    fake_agui_server: Factory, caplog: pytest.LogCaptureFixture
) -> None:
    """REQ-021.6, Art. 3: the header value appears in no log record or error message."""
    headers = {"Authorization": f"Bearer {SECRET}"}
    errors: list[BaseException] = []
    with caplog.at_level(logging.DEBUG):
        for script in (
            [status(401), raw("bad token")],
            [content_type("text/html"), raw("<html>")],
            [STARTED, send("{oops"), raw("data: {")],
            [STARTED, FINISHED],
        ):
            server = fake_agui_server(script)
            client = HttpAGUIClient(server.url, headers=headers)
            try:
                await _collect(client)
            except (AgentHTTPError, AgentStreamError) as exc:
                errors.append(exc)
            await client.aclose()
    assert len(errors) == 3
    assert SECRET not in caplog.text
    for err in errors:
        assert SECRET not in str(err)
        assert SECRET not in repr(err)
    assert repr(HttpAGUIClient("http://x", headers=headers)).count(SECRET) == 0
