"""Exception hierarchy and error codes (API §9, DM §6).

Exceptions are raised to *developers*. The browser only ever sees an :class:`ErrorCode`
and a sanitized message in the state vars.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, TypeAlias

__all__ = [
    "AdapterNotInstalledError",
    "AgentHTTPError",
    "AgentKitError",
    "AgentStreamError",
    "ConfigurationError",
    "ErrorCode",
    "StreamErrorReason",
]


class ErrorCode(StrEnum):
    """Codes surfaced in the ``error_code`` state var (API §9.2). Values equal names."""

    MESSAGE_TOO_LONG = "MESSAGE_TOO_LONG"
    AGENT_RUN_ERROR = "AGENT_RUN_ERROR"
    AGENT_HTTP_ERROR = "AGENT_HTTP_ERROR"
    AGENT_STREAM_ERROR = "AGENT_STREAM_ERROR"
    AGENT_EXCEPTION = "AGENT_EXCEPTION"
    INVALID_EDITED_ARGS = "INVALID_EDITED_ARGS"
    SHARED_STATE_LOCKED = "SHARED_STATE_LOCKED"
    SHARED_STATE_INVALID = "SHARED_STATE_INVALID"
    SHARED_STATE_PATCH_FAILED = "SHARED_STATE_PATCH_FAILED"
    CLIENT_TOOL_LOOP_LIMIT = "CLIENT_TOOL_LOOP_LIMIT"


StreamErrorReason: TypeAlias = Literal["timeout", "eof", "content_type", "connect", "agent_raised"]


class AgentKitError(Exception):
    """Base class of every reflex-agentkit exception."""


class ConfigurationError(AgentKitError, ValueError):
    """Invalid class configuration, tool schema or adapter setup (raised at startup)."""


class AdapterNotInstalledError(AgentKitError, ImportError):
    """An adapter was imported without its optional extra installed (API §7.7)."""


class AgentHTTPError(AgentKitError):
    """The agent endpoint answered with a non-2xx status."""

    def __init__(self, status_code: int, message: str | None = None) -> None:
        self.status_code = status_code
        self._message = message
        super().__init__(message or f"agent endpoint returned HTTP {status_code}")

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.status_code, self._message))


class AgentStreamError(AgentKitError):
    """The event stream failed: timeout, EOF, bad content type, connect, or agent raised."""

    def __init__(self, reason: StreamErrorReason, message: str | None = None) -> None:
        self.reason: StreamErrorReason = reason
        self._message = message
        super().__init__(message or f"agent stream error: {reason}")

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.reason, self._message))
