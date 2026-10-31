"""Smoke test: the package imports and exposes its version."""

import pytest

import reflex_agentkit


def test_package_imports() -> None:
    """REQ-031.1: the package and its pure core import cleanly."""
    import reflex_agentkit.core

    assert reflex_agentkit.__version__ == "0.1.0"


def test_unknown_attribute_raises_attribute_error() -> None:
    """API §1: the lazy ``__getattr__`` rejects unknown names."""
    with pytest.raises(AttributeError):
        _ = reflex_agentkit.does_not_exist


def test_API_3_top_level_reexports_core_names() -> None:
    """API §3: the non-Reflex public names are importable from the package root."""
    from reflex_agentkit import (
        AgentKitError,
        ConfigurationError,
        ErrorCode,
        RunStatus,
        ToolCallStatus,
    )
    from reflex_agentkit.core import errors, models

    assert RunStatus is models.RunStatus
    assert ToolCallStatus is models.ToolCallStatus
    assert ErrorCode is errors.ErrorCode
    assert issubclass(ConfigurationError, AgentKitError)
