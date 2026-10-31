"""Client-side tools: ``client_tool``, ``ClientTool`` and ``invoke`` (T-017, API §6)."""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Callable
from typing import Any

import pytest
from ag_ui.core import Tool

from reflex_agentkit.core.errors import ConfigurationError
from reflex_agentkit.core.tools import ClientTool, client_tool


@client_tool
async def show_chart(title: str, values: list[float], color: str = "blue") -> str:
    """Render a bar chart in the chat.

    The second paragraph is not part of the description.
    """
    return f"{title}:{sum(values)}:{color}"


def test_REQ_018_1_decorator_builds_a_client_tool() -> None:
    """REQ-018.1: name, description and JSON Schema come from the function."""
    assert isinstance(show_chart, ClientTool)
    assert show_chart.name == "show_chart"
    assert show_chart.description == "Render a bar chart in the chat."
    assert show_chart.requires_approval is False
    assert show_chart.timeout_s is None
    params = show_chart.parameters
    assert params["type"] == "object"
    assert params["required"] == ["title", "values"]
    assert params["properties"]["values"]["items"] == {"type": "number"}
    assert params["properties"]["color"]["default"] == "blue"
    assert "title" not in params  # the model's title is not part of the advertised schema


def test_REQ_018_1_decorator_options_override_the_defaults() -> None:
    """API §6: ``name``, ``description``, ``requires_approval`` and ``timeout_s``."""

    @client_tool(name="pick", description="Pick a date.", requires_approval=True, timeout_s=5)
    def pick_date(day: int) -> int:
        return day

    assert (pick_date.name, pick_date.description) == ("pick", "Pick a date.")
    assert (pick_date.requires_approval, pick_date.timeout_s) == (True, 5)


def test_REQ_018_1_to_agui_tool_produces_the_advertised_definition() -> None:
    """REQ-018.1: ``to_agui_tool`` returns an ``ag_ui.core.Tool``."""
    tool = show_chart.to_agui_tool()
    assert tool == Tool(
        name="show_chart", description=show_chart.description, parameters=show_chart.parameters
    )


def test_REQ_018_1_client_tool_is_frozen() -> None:
    """API §6: ``ClientTool`` is a frozen dataclass."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        show_chart.name = "x"  # type: ignore[misc]


def test_REQ_018_1_no_docstring_means_an_empty_description() -> None:
    """API §6: the description defaults to the first docstring paragraph, if any."""

    @client_tool
    def bare() -> None: ...

    assert bare.description == ""
    assert bare.parameters["properties"] == {}


class _Opaque:
    pass


def _no_hint(x):  # type: ignore[no-untyped-def]  # noqa: ANN001
    return x


def _opaque(x: _Opaque) -> None: ...


def _callable(x: Callable[[], int]) -> None: ...


def _varargs(*args: int) -> None: ...


def _kwargs(**kwargs: int) -> None: ...


@pytest.mark.parametrize(
    "func",
    [_no_hint, _opaque, _callable, _varargs, _kwargs],
    ids=["no-hint", "opaque-class", "callable", "varargs", "kwargs"],
)
def test_REQ_018_1_unsupported_parameters_raise_configuration_error(func: Any) -> None:
    """API §6: missing or non-JSON-Schema hints fail at decoration time."""
    with pytest.raises(ConfigurationError):
        client_tool(func)


def test_REQ_018_1_non_callable_is_rejected() -> None:
    """API §6: only functions can be client tools."""
    with pytest.raises(ConfigurationError):
        client_tool(42)  # type: ignore[call-overload]


async def test_REQ_018_2_invoke_runs_an_async_handler_with_parsed_args() -> None:
    """REQ-018.2: the handler gets the validated args; a ``str`` result is sent as-is."""
    ok, text = await show_chart.invoke({"title": "t", "values": [1, 2.5]}, timeout_s=1)
    assert (ok, text) == (True, "t:3.5:blue")


@pytest.mark.parametrize(
    ("result", "expected"),
    [(None, ""), ({"a": [1, "x"]}, '{"a":[1,"x"]}'), (3, "3"), ("plain", "plain")],
    ids=["none", "dict", "int", "str"],
)
async def test_REQ_018_2_results_are_encoded(result: object, expected: str) -> None:
    """API §6: ``str`` as-is, ``None`` as ``""``, anything else JSON-encoded."""

    @client_tool
    def echo() -> object:
        return result

    assert await echo.invoke({}, timeout_s=None) == (True, expected)


async def test_REQ_018_4_a_raising_handler_returns_the_error_text() -> None:
    """REQ-018.4: an exception becomes ``(False, error text)``, never propagates."""

    @client_tool
    async def boom() -> str:
        raise RuntimeError("disk full")

    ok, text = await boom.invoke({}, timeout_s=1)
    assert not ok
    assert "disk full" in text


async def test_REQ_018_4_invalid_args_return_an_error() -> None:
    """REQ-018.4: args that fail validation are reported as a tool error."""
    ok, text = await show_chart.invoke({"title": "t", "values": "nope"}, timeout_s=1)
    assert not ok
    assert "values" in text


async def test_REQ_018_4_unencodable_result_returns_an_error() -> None:
    """REQ-018.4: a result JSON cannot encode is a tool error."""

    @client_tool
    def weird() -> object:
        return _Opaque()

    ok, _ = await weird.invoke({}, timeout_s=None)
    assert not ok


async def test_REQ_018_5_a_slow_handler_times_out() -> None:
    """REQ-018.5: exceeding the timeout is treated as a raised timeout error."""

    @client_tool
    async def slow() -> str:
        await asyncio.sleep(5)
        return "late"

    ok, text = await slow.invoke({}, timeout_s=0.05)
    assert not ok
    assert "timed out" in text.lower()


async def test_REQ_024_2_sync_handler_runs_off_the_event_loop() -> None:
    """REQ-024.2, Art. 4: a blocking sync handler does not stall the loop."""

    @client_tool
    def blocking() -> str:
        time.sleep(0.3)
        return "done"

    ticks = 0

    async def counter() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(counter())
    try:
        assert await blocking.invoke({}, timeout_s=2) == (True, "done")
    finally:
        task.cancel()
    assert ticks >= 10
