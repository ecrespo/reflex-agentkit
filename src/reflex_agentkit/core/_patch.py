"""Typed façade over ``jsonpatch`` for RFC 6902 shared-state deltas (TD DD-007).

This is the only module that imports ``jsonpatch``. Patches are applied to a deep copy,
so a failure anywhere leaves the caller's document untouched (REQ-016.3).
"""

from __future__ import annotations

from typing import Any, cast

import jsonpatch  # type: ignore[import-untyped]  # jsonpatch ships no stubs (DD-007, Art. 7)

from reflex_agentkit.core.models import JsonObject

__all__ = ["PatchError", "apply_patch"]

_PATCH_FAILURES: tuple[type[BaseException], ...] = (
    jsonpatch.JsonPatchException,
    jsonpatch.JsonPointerException,
    AttributeError,
    IndexError,
    KeyError,
    RecursionError,  # pathologically deep documents or values
    TypeError,
    ValueError,
)


class PatchError(Exception):
    """An RFC 6902 patch could not be applied; the input is unchanged."""


def apply_patch(doc: JsonObject, ops: list[JsonObject]) -> JsonObject:
    """Apply ``ops`` atomically to a deep copy of ``doc`` and return the result.

    Raises:
        PatchError: on any failure (bad path, failed ``test`` op, malformed operation,
            or a result that is not a JSON object).
    """
    try:
        result: Any = jsonpatch.apply_patch(doc, ops, in_place=False)
    except _PATCH_FAILURES as exc:
        raise PatchError(f"JSON Patch failed: {exc}") from exc
    if not isinstance(result, dict):
        raise PatchError("JSON Patch failed: the result is not a JSON object")
    return cast(JsonObject, result)
