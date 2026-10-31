"""Client-side tools: Python handlers the agent calls and the app executes (API §6).

``@client_tool`` turns a function into a frozen :class:`ClientTool` whose JSON Schema
``parameters`` come from the type hints (via a pydantic model). ``ClientTool.invoke``
validates the arguments, runs the handler (sync handlers in a worker thread, Constitution
Art. 4) under a timeout and returns ``(ok, text)``: handler failures are tool results,
never exceptions (REQ-018.4).
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import inspect
import typing
from collections.abc import Callable
from typing import Any, overload

import pydantic
import pydantic_core
from ag_ui.core import Tool

from reflex_agentkit.core.errors import ConfigurationError

__all__ = ["ClientTool", "client_tool"]

Handler = Callable[..., Any]


@dataclasses.dataclass(frozen=True, slots=True)
class ClientTool:
    """A tool advertised to the agent and executed in the app (API §6)."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler = dataclasses.field(repr=False)
    requires_approval: bool = False
    timeout_s: float | None = None
    _model: type[pydantic.BaseModel] = dataclasses.field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_model", _model_for(self.handler, self.name))

    def to_agui_tool(self) -> Tool:
        """The definition sent in ``RunAgentInput.tools`` (REQ-018.1)."""
        return Tool(name=self.name, description=self.description, parameters=self.parameters)

    async def invoke(self, args: dict[str, Any], timeout_s: float | None) -> tuple[bool, str]:
        """Run the handler with ``args``; return ``(ok, result text)`` (REQ-018.2, 018.4-5).

        Args:
            args: The parsed (or edited) call arguments.
            timeout_s: Seconds before the call is treated as failed; ``None`` for no limit.
                A timed-out sync handler's thread cannot be interrupted and runs to
                completion in the background; its result is discarded.
        """
        try:
            validated = self._model.model_validate(args)
        except pydantic.ValidationError as exc:
            return False, f"Invalid tool arguments: {exc}"
        kwargs = {name: getattr(validated, name) for name in type(validated).model_fields}
        try:
            async with asyncio.timeout(timeout_s):
                result = await self._call(kwargs)
        except TimeoutError:
            return False, f"The tool timed out after {timeout_s} s."
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        return _encode(result)

    async def _call(self, kwargs: dict[str, Any]) -> Any:
        if inspect.iscoroutinefunction(self.handler):
            return await self.handler(**kwargs)
        result = await asyncio.to_thread(self.handler, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result


def _encode(result: Any) -> tuple[bool, str]:
    """``str`` as-is, ``None`` as ``""``, anything else as compact JSON (API §6)."""
    if result is None:
        return True, ""
    if isinstance(result, str):
        return True, result
    try:
        return True, pydantic_core.to_json(result).decode()
    except pydantic_core.PydanticSerializationError as exc:
        return False, f"The tool result is not JSON-encodable: {exc}"


def _description(func: Handler) -> str:
    doc = inspect.getdoc(func)
    if not doc:
        return ""
    return " ".join(doc.split("\n\n", 1)[0].split())


def _model_for(func: Handler, name: str) -> type[pydantic.BaseModel]:
    """A pydantic model of ``func``'s parameters; ``ConfigurationError`` if unsupported."""
    try:
        signature = inspect.signature(func)
        target = func.func if isinstance(func, functools.partial) else func
        hints = typing.get_type_hints(target, include_extras=True)
    except (TypeError, ValueError, NameError) as exc:
        raise ConfigurationError(f"client tool {name!r}: cannot read its signature: {exc}") from exc
    fields: dict[str, Any] = {}
    for param in signature.parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD, param.POSITIONAL_ONLY):
            raise ConfigurationError(
                f"client tool {name!r}: parameter {param.name!r} must be a named parameter"
            )
        if param.name not in hints:
            raise ConfigurationError(
                f"client tool {name!r}: parameter {param.name!r} has no type hint"
            )
        default = ... if param.default is param.empty else param.default
        fields[param.name] = (hints[param.name], default)
    try:
        model: type[pydantic.BaseModel] = pydantic.create_model(f"{name}_args", **fields)
        model.model_json_schema()
    except (pydantic.PydanticUserError, NameError, TypeError) as exc:
        raise ConfigurationError(
            f"client tool {name!r}: its parameters cannot be described as JSON Schema: {exc}"
        ) from exc
    return model


def _build(
    func: Handler,
    *,
    name: str | None,
    description: str | None,
    requires_approval: bool,
    timeout_s: float | None,
) -> ClientTool:
    if not callable(func):
        raise ConfigurationError(f"client_tool expects a function, got {type(func).__name__}")
    tool_name = name or getattr(func, "__name__", "")
    if not tool_name:
        raise ConfigurationError("client_tool: the tool needs a name")
    model = _model_for(func, tool_name)
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.setdefault("properties", {})
    return ClientTool(
        name=tool_name,
        description=_description(func) if description is None else description,
        parameters=schema,
        handler=func,
        requires_approval=requires_approval,
        timeout_s=timeout_s,
    )


@overload
def client_tool(func: Handler, /) -> ClientTool: ...


@overload
def client_tool(
    *,
    name: str | None = None,
    description: str | None = None,
    requires_approval: bool = False,
    timeout_s: float | None = None,
) -> Callable[[Handler], ClientTool]: ...


def client_tool(
    func: Handler | None = None,
    /,
    *,
    name: str | None = None,
    description: str | None = None,
    requires_approval: bool = False,
    timeout_s: float | None = None,
) -> ClientTool | Callable[[Handler], ClientTool]:
    """Declare a client-side tool (API §6, REQ-018.1).

    Usable bare (``@client_tool``) or with options (``@client_tool(requires_approval=True)``).

    Args:
        func: The handler, ``async def`` or plain ``def``.
        name: Tool name; defaults to the function name.
        description: Defaults to the first paragraph of the docstring.
        requires_approval: Whether each call waits for ``approve_tool`` (REQ-018.3).
        timeout_s: Per-call timeout; ``None`` uses ``AgentState.client_tool_timeout_s``.

    Raises:
        ConfigurationError: A parameter has no type hint or one that cannot be expressed
            as JSON Schema, or the parameters use ``*args``/``**kwargs``/positional-only.
    """
    options: dict[str, Any] = {
        "name": name,
        "description": description,
        "requires_approval": requires_approval,
        "timeout_s": timeout_s,
    }
    if func is None:
        return lambda f: _build(f, **options)
    return _build(func, **options)
