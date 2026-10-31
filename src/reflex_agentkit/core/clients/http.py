"""``HttpAGUIClient``: AG-UI over HTTP + SSE (API §7.3, §8).

The client POSTs the ``RunAgentInput`` as camelCase JSON and decodes the SSE response
into validated events. Transport failures become ``AgentHTTPError`` or
``AgentStreamError``; it never yields a synthetic ``RUN_ERROR``. Headers (often API
keys) are sent upstream only: they are never logged, stored, or put in an exception
message (REQ-021.3, REQ-021.6, Constitution Art. 3).
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping

import httpx
from ag_ui.core import BaseEvent, EventType, RunAgentInput

from reflex_agentkit.core.clients.base import validate_event
from reflex_agentkit.core.clients.sse import SSEParser
from reflex_agentkit.core.errors import AgentHTTPError, AgentStreamError

__all__ = ["DEFAULT_TIMEOUT", "HttpAGUIClient"]

logger = logging.getLogger("reflex_agentkit.core.clients.http")

DEFAULT_TIMEOUT = httpx.Timeout(10.0, read=60.0)
BODY_EXCERPT_BYTES = 1024
_TERMINAL = frozenset({EventType.RUN_FINISHED, EventType.RUN_ERROR})

HeadersSource = Mapping[str, str] | Callable[[], Mapping[str, str]]


class HttpAGUIClient:
    """Streams a run from an AG-UI HTTP endpoint (REQ-021.2-4, REQ-021.6).

    Safe to share across sessions: it keeps no per-run state.

    Args:
        url: The AG-UI endpoint.
        headers: Static headers, or a callable evaluated per run (rotating tokens).
        timeout: An ``httpx.Timeout`` or seconds; ``read`` bounds the gap between bytes.
        http_client: A caller-owned ``httpx.AsyncClient``; ``aclose()`` leaves it open.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: HeadersSource | None = None,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._headers = headers
        self._timeout = timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
        self._injected = http_client
        self._owned: httpx.AsyncClient | None = None

    def __repr__(self) -> str:
        return f"{type(self).__name__}(url={self._url!r})"

    def _client(self) -> httpx.AsyncClient:
        if self._injected is not None:
            return self._injected
        if self._owned is None or self._owned.is_closed:
            self._owned = httpx.AsyncClient()
        return self._owned

    def _request_headers(self) -> dict[str, str]:
        extra = self._headers() if callable(self._headers) else (self._headers or {})
        return {**extra, "Content-Type": "application/json", "Accept": "text/event-stream"}

    async def stream(self, run_input: RunAgentInput) -> AsyncIterator[BaseEvent]:
        """POST ``run_input``; yield validated events until a terminal one (API §8.2)."""
        body = run_input.model_dump_json(by_alias=True, exclude_none=True)
        try:
            async with self._client().stream(
                "POST",
                self._url,
                content=body,
                headers=self._request_headers(),
                timeout=self._timeout,
            ) as response:
                await _check(response)
                parser = SSEParser()
                async for chunk in response.aiter_bytes():
                    for data in parser.feed(chunk):
                        event = _decode(data)
                        if event is None:
                            continue
                        yield event
                        if event.type in _TERMINAL:
                            return
                parser.finish()
        except httpx.ReadTimeout:
            raise AgentStreamError(
                "timeout", "read timeout: the agent sent nothing in time"
            ) from None
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise AgentStreamError(
                "connect", f"cannot connect to the agent ({type(exc).__name__})"
            ) from None
        except httpx.TransportError as exc:
            raise AgentStreamError(
                "eof", f"connection to the agent lost ({type(exc).__name__})"
            ) from None
        raise AgentStreamError("eof", "stream ended unexpectedly")

    async def aclose(self) -> None:
        """Close the owned ``httpx.AsyncClient``, if any. Idempotent."""
        owned, self._owned = self._owned, None
        if owned is not None:
            await owned.aclose()


async def _check(response: httpx.Response) -> None:
    """Raise for non-2xx status and non-SSE content types (API §8.2)."""
    if not response.is_success:
        excerpt = await _excerpt(response)
        logger.debug(
            "agent endpoint returned HTTP %s; body excerpt: %s", response.status_code, excerpt
        )
        raise AgentHTTPError(response.status_code)
    media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "text/event-stream":
        raise AgentStreamError(
            "content_type", f"unexpected content type {media_type or '<none>'!r}"
        )


async def _excerpt(response: httpx.Response) -> str:
    collected = b""
    async for chunk in response.aiter_bytes():
        collected += chunk
        if len(collected) >= BODY_EXCERPT_BYTES:
            break
    return collected[:BODY_EXCERPT_BYTES].decode(errors="replace")


def _decode(data: str) -> BaseEvent | None:
    try:
        raw = json.loads(data)
    except ValueError:
        logger.warning("skipped an SSE frame that is not valid JSON")
        return None
    return validate_event(raw)
