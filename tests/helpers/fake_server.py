"""A scripted AG-UI SSE server for integration tests (T-021, TD DD-010).

A plain ASGI app served by ``uvicorn`` on an ephemeral port in a background thread. A
real server (rather than a mock transport) lets tests observe that the *server* sees the
client disconnect (REQ-007.2). Each request plays the same script::

    server = fake_agui_server([send(event), sleep(0.1), send(event2), hang()])
    server.url, server.requests, server.disconnected

Steps: ``send(event)`` (an event object, a dict or a raw data string), ``reply(build)``
(an event built from the parsed request body, e.g. to echo its run IDs), ``raw(text)``
(bytes written verbatim), ``sleep(s)``, ``status(code)``, ``content_type(ct)`` (both
before the first body step), ``close()`` (end the response; implied at the script's end)
``hang()`` (stay open until the client goes away) and ``abort()`` (drop the connection).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import socket
import threading
import time
from collections.abc import Awaitable, Callable, Iterator, Sequence
from typing import Any

import pytest
import uvicorn
from ag_ui.core import BaseEvent

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


@dataclasses.dataclass(frozen=True)
class Step:
    """One scripted action."""

    kind: str
    value: Any = None


def send(event: BaseEvent | dict[str, Any] | str) -> Step:
    """Write one SSE frame whose data is the JSON event (or the given string)."""
    if isinstance(event, BaseEvent):
        data = event.model_dump_json(by_alias=True, exclude_none=True)
    elif isinstance(event, dict):
        data = json.dumps(event)
    else:
        data = event
    return Step("raw", f"data: {data}\n\n")


def reply(build: Callable[[Any], BaseEvent | dict[str, Any]]) -> Step:
    """Write one SSE frame whose event is built from the parsed request body."""
    return Step("reply", build)


def raw(text: str) -> Step:
    """Write ``text`` verbatim (for framing edge cases)."""
    return Step("raw", text)


def sleep(seconds: float) -> Step:
    return Step("sleep", seconds)


def status(code: int) -> Step:
    return Step("status", code)


def content_type(value: str) -> Step:
    return Step("content_type", value)


def close() -> Step:
    return Step("close")


def hang() -> Step:
    return Step("hang")


def abort() -> Step:
    """Drop the connection mid-response (the app raises; uvicorn closes the socket)."""
    return Step("abort")


@dataclasses.dataclass(frozen=True)
class RecordedRequest:
    """What the server received."""

    method: str
    path: str
    headers: dict[str, str]
    body: Any


class FakeServer:
    """A running fake AG-UI server."""

    def __init__(self, script: Sequence[Step]) -> None:
        self.script = list(script)
        self.requests: list[RecordedRequest] = []
        self.disconnected = threading.Event()
        self.url = ""
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    # --- ASGI ------------------------------------------------------------------------

    async def __call__(self, scope: Scope, receive: Receive, send_: Send) -> None:
        if scope["type"] != "http":  # pragma: no cover - lifespan is off
            return
        body = b""
        while True:
            message = await receive()
            body += message.get("body", b"")
            if not message.get("more_body"):
                break
        try:
            parsed: Any = json.loads(body) if body else None
        except ValueError:
            parsed = body.decode(errors="replace")
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        self.requests.append(RecordedRequest(scope["method"], scope["path"], headers, parsed))

        state = {"completed": False}
        gone = asyncio.Event()

        async def watch() -> None:
            message = await receive()
            if message["type"] == "http.disconnect":
                gone.set()
                if not state["completed"]:
                    self.disconnected.set()

        watcher = asyncio.create_task(watch())
        try:
            await self._play(send_, state, gone, parsed)
        finally:
            if not watcher.done():
                await asyncio.wait({watcher}, timeout=0.5)
            watcher.cancel()

    async def _play(
        self, send_: Send, state: dict[str, bool], gone: asyncio.Event, body: Any
    ) -> None:
        code, ctype, started = 200, "text/event-stream", False

        async def start() -> None:
            nonlocal started
            if not started:
                started = True
                await send_(
                    {
                        "type": "http.response.start",
                        "status": code,
                        "headers": [(b"content-type", ctype.encode())],
                    }
                )

        for step in self.script:
            if gone.is_set():
                return
            if step.kind == "status":
                code = step.value
            elif step.kind == "content_type":
                ctype = step.value
            elif step.kind in ("raw", "reply"):
                text = send(step.value(body)).value if step.kind == "reply" else step.value
                await start()
                await send_(
                    {"type": "http.response.body", "body": text.encode(), "more_body": True}
                )
            elif step.kind == "sleep":
                await start()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(gone.wait(), step.value)
            elif step.kind == "hang":
                await start()
                await gone.wait()
                return
            elif step.kind == "close":
                break
            elif step.kind == "abort":
                await start()
                raise ConnectionAbortedError("scripted abort")
        await start()
        state["completed"] = True
        await send_({"type": "http.response.body", "body": b"", "more_body": False})

    # --- lifecycle -------------------------------------------------------------------

    def start(self) -> FakeServer:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        config = uvicorn.Config(
            self, lifespan="off", log_level="warning", timeout_graceful_shutdown=1
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [sock]}, daemon=True
        )
        self._thread.start()
        deadline = time.monotonic() + 5
        while not self._server.started:
            if time.monotonic() > deadline:  # pragma: no cover - environment failure
                raise RuntimeError("fake AG-UI server did not start")
            time.sleep(0.01)
        self.url = f"http://127.0.0.1:{sock.getsockname()[1]}/agent"
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)


@pytest.fixture
def fake_agui_server() -> Iterator[Callable[[Sequence[Step]], FakeServer]]:
    """Factory fixture: ``fake_agui_server(script)`` starts a server; all stop at teardown."""
    servers: list[FakeServer] = []

    def factory(script: Sequence[Step]) -> FakeServer:
        server = FakeServer(script).start()
        servers.append(server)
        return server

    yield factory
    for server in servers:
        server.stop()
