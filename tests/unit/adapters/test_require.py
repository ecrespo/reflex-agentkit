"""Adapter import guard (T-032, REQ-031.3, API §7.7)."""

from __future__ import annotations

import importlib
import sys

import pytest

from reflex_agentkit.adapters._require import require
from reflex_agentkit.core.errors import AdapterNotInstalledError

MESSAGE = (
    "reflex_agentkit.adapters.pydantic_ai requires the 'pydantic-ai' extra: "
    "pip install 'reflex-agentkit[pydantic-ai]'"
)


def test_REQ_031_3_require_passes_when_installed() -> None:
    """An installed module is imported silently."""
    require("pydantic-ai", "json")


def test_REQ_031_3_require_raises_the_documented_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """API §7.7: the exact message; the error is an ``ImportError``."""
    monkeypatch.setitem(sys.modules, "pydantic_ai", None)
    with pytest.raises(AdapterNotInstalledError) as info:
        require("pydantic-ai", "pydantic_ai")
    assert str(info.value) == MESSAGE
    assert isinstance(info.value, ImportError)


def test_REQ_031_3_importing_the_adapter_without_the_extra_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """REQ-031.3: importing ``adapters.pydantic_ai`` without the extra raises at import."""
    monkeypatch.setitem(sys.modules, "pydantic_ai", None)
    monkeypatch.delitem(sys.modules, "reflex_agentkit.adapters.pydantic_ai", raising=False)
    with pytest.raises(AdapterNotInstalledError, match="pydantic-ai"):
        importlib.import_module("reflex_agentkit.adapters.pydantic_ai")
