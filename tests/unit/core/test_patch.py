"""RFC 6902 JSON Patch façade (TD DD-007; REQ-016.2, REQ-016.3)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from reflex_agentkit.core._patch import PatchError, apply_patch
from reflex_agentkit.core.models import JsonObject

SRC = Path(__file__).resolve().parents[3] / "src"


def _doc() -> JsonObject:
    return {"todos": [{"title": "a", "done": False}], "count": 1, "meta": {"owner": "me"}}


@pytest.mark.parametrize(
    ("ops", "expected"),
    [
        (
            [{"op": "add", "path": "/todos/-", "value": {"title": "b", "done": False}}],
            {"todos": [{"title": "a", "done": False}, {"title": "b", "done": False}]},
        ),
        ([{"op": "remove", "path": "/meta"}], {"meta": None}),
        ([{"op": "replace", "path": "/count", "value": 2}], {"count": 2}),
        ([{"op": "move", "from": "/meta/owner", "path": "/owner"}], {"owner": "me", "meta": {}}),
        ([{"op": "copy", "from": "/count", "path": "/copy"}], {"copy": 1, "count": 1}),
        ([{"op": "test", "path": "/count", "value": 1}], {"count": 1}),
    ],
    ids=["add", "remove", "replace", "move", "copy", "test"],
)
def test_REQ_016_2_applies_every_rfc6902_operation(
    ops: list[JsonObject], expected: dict[str, Any]
) -> None:
    """REQ-016.2: each RFC 6902 operation is applied to the shared state."""
    result = apply_patch(_doc(), ops)
    for key, value in expected.items():
        if value is None:
            assert key not in result
        else:
            assert result[key] == value


def test_REQ_016_2_does_not_mutate_the_input() -> None:
    """REQ-016.2, DM R-2: the input document is never modified."""
    doc = _doc()
    before = copy.deepcopy(doc)
    result = apply_patch(doc, [{"op": "add", "path": "/todos/0/done", "value": True}])
    assert doc == before
    assert result["todos"][0]["done"] is True  # type: ignore[index,call-overload]
    assert result["todos"] is not doc["todos"]


def test_REQ_016_3_a_failing_middle_op_leaves_the_input_unchanged() -> None:
    """REQ-016.3: the patch is atomic; a failure in the middle applies nothing."""
    doc = _doc()
    before = copy.deepcopy(doc)
    ops: list[JsonObject] = [
        {"op": "replace", "path": "/count", "value": 99},
        {"op": "remove", "path": "/does/not/exist"},
        {"op": "replace", "path": "/meta/owner", "value": "you"},
    ]
    with pytest.raises(PatchError):
        apply_patch(doc, ops)
    assert doc == before


@pytest.mark.parametrize(
    "ops",
    [
        [{"op": "remove", "path": "/nope"}],
        [{"op": "replace", "path": "/todos/7/title", "value": "x"}],
        [{"op": "test", "path": "/count", "value": 2}],
        [{"op": "frobnicate", "path": "/count"}],
        [{"path": "/count", "value": 1}],
        [{"op": "add", "path": "", "value": [1, 2]}],
    ],
    ids=["bad-path", "bad-index", "failed-test", "unknown-op", "missing-op", "non-object-root"],
)
def test_REQ_016_3_any_failure_raises_patch_error(ops: list[JsonObject]) -> None:
    """REQ-016.3: every failure, including a failed ``test`` op, raises ``PatchError``."""
    with pytest.raises(PatchError):
        apply_patch(_doc(), ops)


def test_REQ_016_3_patch_error_keeps_the_upstream_cause() -> None:
    """REQ-016.3: the warning can name the cause of the failure."""
    with pytest.raises(PatchError) as info:
        apply_patch(_doc(), [{"op": "remove", "path": "/nope"}])
    assert info.value.__cause__ is not None


def test_DD_007_jsonpatch_is_imported_only_by_the_facade() -> None:
    """DD-007: ``core/_patch.py`` is the only module that imports ``jsonpatch``."""
    importers = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "import jsonpatch" in path.read_text(encoding="utf-8")
    ]
    assert importers == ["reflex_agentkit/core/_patch.py"]


def test_REQ_016_3_pathologically_deep_documents_raise_patch_error() -> None:
    """REQ-005.1, REQ-016.3: a document deep enough to exhaust recursion is a PatchError."""
    deep: JsonObject = {}
    node = deep
    for _ in range(100_000):
        child: JsonObject = {}
        node["n"] = child
        node = child
    with pytest.raises(PatchError):
        apply_patch(deep, [{"op": "add", "path": "/x", "value": 1}])
