"""Smoke test: the package imports and exposes its version."""

import pytest

import reflex_agentkit


def test_package_imports() -> None:
    """REQ-031.1: the package and its pure core import cleanly."""
    import reflex_agentkit.core

    assert reflex_agentkit.__version__ == "0.1.0.dev0"


def test_unknown_attribute_raises_attribute_error() -> None:
    """API §1: the lazy ``__getattr__`` rejects unknown names."""
    with pytest.raises(AttributeError):
        _ = reflex_agentkit.does_not_exist
