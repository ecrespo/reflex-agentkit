"""The weekly latest-dependencies workflow (T-049, DD-001)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "deps-latest.yml"


def _workflow() -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text())
    return loaded


def test_DD_001_deps_latest_runs_weekly_and_on_demand() -> None:
    """It runs on a weekly schedule and can be started by hand."""
    triggers = _workflow()[True]  # YAML 1.1 reads the ``on`` key as True
    assert len(triggers["schedule"]) == 1
    assert "workflow_dispatch" in triggers


def test_DD_001_deps_latest_never_blocks_or_writes_the_repository() -> None:
    """``continue-on-error``; read-only contents; the upgrade happens in a temporary copy."""
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["latest"]
    assert job["continue-on-error"] is True
    assert job["permissions"] == {"contents": "read", "issues": "write"}
    steps = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "mktemp -d" in steps
    assert "uv lock --upgrade" in steps
    assert "git push" not in steps
    assert "git commit" not in steps


def test_DD_001_deps_latest_reports_failures_in_an_issue() -> None:
    """A failure opens an issue, or comments on the open one."""
    last = _workflow()["jobs"]["latest"]["steps"][-1]
    assert last["if"] == "failure()"
    assert "gh issue create" in last["run"]
    assert "gh issue comment" in last["run"]
