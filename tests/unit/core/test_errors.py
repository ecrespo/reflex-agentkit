"""Exception hierarchy and error codes (API §9, DM §6)."""

from __future__ import annotations

import pickle

import pytest

from reflex_agentkit.core.errors import (
    AdapterNotInstalledError,
    AgentHTTPError,
    AgentKitError,
    AgentStreamError,
    ConfigurationError,
    ErrorCode,
)

DM_ERROR_CODES = {
    "MESSAGE_TOO_LONG",
    "AGENT_RUN_ERROR",
    "AGENT_HTTP_ERROR",
    "AGENT_STREAM_ERROR",
    "AGENT_EXCEPTION",
    "INVALID_EDITED_ARGS",
    "SHARED_STATE_LOCKED",
    "SHARED_STATE_INVALID",
    "SHARED_STATE_PATCH_FAILED",
    "CLIENT_TOOL_LOOP_LIMIT",
}


def test_DM_6_error_code_values_are_their_uppercase_names() -> None:
    """DM §6: ``ErrorCode`` has exactly the normative values, each equal to its name."""
    assert {code.value for code in ErrorCode} == DM_ERROR_CODES
    for code in ErrorCode:
        assert code == code.name
    assert ErrorCode.MESSAGE_TOO_LONG == "MESSAGE_TOO_LONG"


def test_API_9_1_configuration_error_is_a_value_error() -> None:
    """API §9.1: ``ConfigurationError`` subclasses both ``AgentKitError`` and ``ValueError``."""
    err = ConfigurationError("bad config")
    assert isinstance(err, AgentKitError)
    assert isinstance(err, ValueError)


def test_API_9_1_adapter_not_installed_error_is_an_import_error() -> None:
    """API §9.1, §7.7: ``AdapterNotInstalledError`` is an ``ImportError``."""
    err = AdapterNotInstalledError("missing extra")
    assert isinstance(err, AgentKitError)
    assert isinstance(err, ImportError)


def test_API_9_1_agent_http_error_carries_the_status_code() -> None:
    """API §9.1: ``AgentHTTPError.status_code`` is kept, and the message names it."""
    err = AgentHTTPError(503)
    assert isinstance(err, AgentKitError)
    assert err.status_code == 503
    assert "503" in str(err)


def test_API_9_1_agent_stream_error_carries_the_reason() -> None:
    """API §9.1: ``AgentStreamError.reason`` is one of the documented reasons."""
    err = AgentStreamError("timeout", "read timed out")
    assert isinstance(err, AgentKitError)
    assert err.reason == "timeout"
    assert "read timed out" in str(err)


@pytest.mark.parametrize(
    "err",
    [
        ConfigurationError("x"),
        AdapterNotInstalledError("y"),
        AgentHTTPError(404, "not found"),
        AgentStreamError("eof", "stream ended"),
    ],
)
def test_API_9_1_errors_pickle_with_their_attributes(err: AgentKitError) -> None:
    """API §9.1: errors cross process boundaries (Redis, workers) intact."""
    clone = pickle.loads(pickle.dumps(err))  # noqa: S301  # round-trip of our own object
    assert type(clone) is type(err)
    assert str(clone) == str(err)
    assert vars(clone) == vars(err)
